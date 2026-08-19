"""The BYO-key contract: where credentials come from, and what goes on the wire.

No key is ever committed and no test touches the network — `praxis.llm._urlopen` is
the only seam, and every routing mode is exercised against a mocked response.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import llm  # noqa: E402

# Env vars that would otherwise leak a developer's real credentials into a test.
LEAKY = (
    "PRAXIS_LLM_PROVIDER",
    "PRAXIS_LLM_MODEL",
    "PRAXIS_LLM_API_KEY",
    "PRAXIS_LLM_BASE_URL",
    "PRAXIS_LLM_TIMEOUT",
    "PRAXIS_CONFIG",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AGORA_BASE_URL",
    "AGORA_API_KEY",
    "AGORA_ROUTE",
    "AGORA_FALLBACK_MODELS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in LEAKY:
        monkeypatch.delenv(name, raising=False)
    # Never read the developer's real ~/.config/praxis/config.json.
    monkeypatch.setattr(llm, "default_config_path", lambda: tmp_path / "missing.json")


class _Response(io.BytesIO):
    """Just enough of an http response for `with _urlopen(...) as r: r.read()`."""

    def __init__(self, data: bytes, headers: dict | None = None):
        super().__init__(data)
        # Only set when a test says so: a response with no headers at all is the
        # normal case, and the client has to survive it.
        if headers is not None:
            self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def captured(monkeypatch):
    """Mock the network; record the request and reply with a canned body."""
    calls: list[dict] = []
    body = {"payload": None, "headers": None}

    def fake_urlopen(request, timeout):
        calls.append(
            {
                "url": request.full_url,
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "json": json.loads(request.data),
                "timeout": timeout,
            }
        )
        return _Response(json.dumps(body["payload"]).encode(), body["headers"])

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    return calls, body


ANTHROPIC_REPLY = {"content": [{"type": "text", "text": "hello from anthropic"}]}
OPENAI_REPLY = {"choices": [{"message": {"content": "hello from openai"}}]}


# --- config resolution ---------------------------------------------------


def test_provider_is_inferred_from_whichever_key_is_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = llm.load_config()
    assert config.provider == "openai"
    assert config.api_key == "sk-test"
    assert config.model == llm.DEFAULT_MODEL["openai"]


def test_explicit_provider_and_model_win(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("PRAXIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PRAXIS_LLM_MODEL", "claude-sonnet-5")
    config = llm.load_config()
    assert (config.provider, config.model) == ("anthropic", "claude-sonnet-5")


def test_local_needs_only_a_base_url(monkeypatch):
    monkeypatch.setenv("PRAXIS_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    config = llm.load_config()
    assert config.provider == "local"
    assert config.api_key == ""
    # The trailing /v1 is normalized away, not doubled up.
    assert config.endpoint == "http://127.0.0.1:1234/v1/chat/completions"


def test_config_file_supplies_provider_and_key_when_env_is_empty(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"provider": "openai", "api_key": "sk-file"}}))
    monkeypatch.setenv("PRAXIS_CONFIG", str(path))
    config = llm.load_config()
    assert (config.provider, config.api_key) == ("openai", "sk-file")


def test_env_beats_the_config_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"provider": "openai", "api_key": "sk-file"}))
    monkeypatch.setenv("PRAXIS_CONFIG", str(path))
    monkeypatch.setenv("PRAXIS_LLM_API_KEY", "sk-env")
    assert llm.load_config().api_key == "sk-env"


def test_no_provider_and_no_key_is_a_config_error():
    with pytest.raises(llm.LLMConfigError):
        llm.load_config()


def test_a_keyless_hosted_provider_is_a_config_error(monkeypatch):
    monkeypatch.setenv("PRAXIS_LLM_PROVIDER", "anthropic")
    with pytest.raises(llm.LLMConfigError, match="ANTHROPIC_API_KEY"):
        llm.load_config()


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("PRAXIS_LLM_PROVIDER", "gemini")
    with pytest.raises(llm.LLMConfigError, match="unknown provider"):
        llm.load_config()


# --- timeout: the knob a slow local model needs --------------------------


def test_timeout_defaults_and_reaches_the_client(monkeypatch):
    """No plumbing: a client built with no argument follows the resolved config."""
    monkeypatch.setenv("PRAXIS_LLM_BASE_URL", "http://127.0.0.1:1234")
    assert llm.load_config().timeout == llm.DEFAULT_TIMEOUT

    monkeypatch.setenv("PRAXIS_LLM_TIMEOUT", "900")
    assert llm.load_config().timeout == 900.0
    assert llm.LLMClient().timeout == 900.0
    # An explicit argument still wins over the environment.
    assert llm.LLMClient(timeout=5).timeout == 5


def test_timeout_comes_from_the_config_file_too(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"base_url": "http://127.0.0.1:1234",
                                        "timeout": 600}}))
    monkeypatch.setenv("PRAXIS_CONFIG", str(path))
    assert llm.load_config().timeout == 600.0


@pytest.mark.parametrize("bad", ["soon", "0", "-30"])
def test_an_unusable_timeout_is_a_config_error(monkeypatch, bad):
    """Loud at startup, not two minutes into a construction run."""
    monkeypatch.setenv("PRAXIS_LLM_BASE_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("PRAXIS_LLM_TIMEOUT", bad)
    with pytest.raises(llm.LLMConfigError, match="PRAXIS_LLM_TIMEOUT"):
        llm.load_config()


# --- routing mode: direct ------------------------------------------------


def test_anthropic_direct_uses_the_messages_api(monkeypatch, captured):
    calls, body = captured
    body["payload"] = ANTHROPIC_REPLY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

    client = llm.LLMClient()
    assert client.config.routed_via_agora is False
    assert client.complete("hi", system="be brief") == "hello from anthropic"

    (call,) = calls
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-ant"
    assert call["headers"]["anthropic-version"] == llm.ANTHROPIC_VERSION
    assert "authorization" not in call["headers"]
    assert call["json"]["model"] == llm.DEFAULT_MODEL["anthropic"]
    assert call["json"]["system"] == "be brief"
    assert call["json"]["messages"] == [{"role": "user", "content": "hi"}]


def test_openai_direct_uses_chat_completions(monkeypatch, captured):
    calls, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")

    assert llm.LLMClient().complete("hi", system="be brief") == "hello from openai"

    (call,) = calls
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["authorization"] == "Bearer sk-oai"
    assert "x-api-key" not in call["headers"]
    assert call["json"]["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]


def test_local_endpoint_speaks_openai_and_sends_no_auth(monkeypatch, captured):
    calls, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("PRAXIS_LLM_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("PRAXIS_LLM_MODEL", "qwen2.5-coder")

    assert llm.LLMClient().complete("hi") == "hello from openai"

    (call,) = calls
    assert call["url"] == "http://localhost:8000/v1/chat/completions"
    assert "authorization" not in call["headers"]
    assert call["json"]["model"] == "qwen2.5-coder"


# --- routing mode: agora -------------------------------------------------


def test_agora_base_url_reroutes_an_anthropic_config(monkeypatch, captured):
    """AGORA_BASE_URL set -> the provider-router, in its OpenAI-compatible format."""
    calls, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")

    client = llm.LLMClient()
    assert client.config.routed_via_agora is True
    assert client.complete("hi") == "hello from openai"

    (call,) = calls
    assert call["url"] == "http://localhost:9000/v1/chat/completions"
    # The router authenticates, not the provider; the model passes through untouched.
    assert call["headers"]["authorization"] == "Bearer sk-ant"
    assert "x-api-key" not in call["headers"]
    assert call["json"]["model"] == llm.DEFAULT_MODEL["anthropic"]


def test_agora_api_key_overrides_the_provider_key(monkeypatch, captured):
    calls, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.setenv("AGORA_API_KEY", "sk-agora")

    llm.LLMClient().complete("hi")
    assert calls[0]["headers"]["authorization"] == "Bearer sk-agora"
    assert calls[0]["url"] == "http://localhost:9000/v1/chat/completions"


def test_agora_needs_no_provider_key(monkeypatch, captured):
    """A loopback router may be unauthenticated — that must not be a config error."""
    _, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("PRAXIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")

    assert llm.LLMClient().complete("hi") == "hello from openai"


# --- routing mode: agora, deeper than a base-URL swap --------------------


def test_router_hints_ride_in_headers_and_never_in_the_payload(monkeypatch, captured):
    """A route or a fallback list must not become a body key a provider rejects."""
    calls, body = captured
    body["payload"] = OPENAI_REPLY
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    monkeypatch.setenv("AGORA_ROUTE", "cheap-and-fast")
    monkeypatch.setenv("AGORA_FALLBACK_MODELS", "claude-opus-5, gpt-4o ,")

    client = llm.LLMClient()
    assert client.config.agora_fallbacks == ("claude-opus-5", "gpt-4o")
    client.complete("hi")

    (call,) = calls
    assert call["headers"][llm.AGORA_ROUTE_HEADER] == "cheap-and-fast"
    assert call["headers"][llm.AGORA_FALLBACK_HEADER] == "claude-opus-5,gpt-4o"
    # The payload is still the plain chat-completions one: no sampling params, and
    # nothing agora-specific for an upstream model to choke on.
    assert set(call["json"]) == {"model", "max_tokens", "messages"}


def test_the_router_reports_what_it_actually_served(monkeypatch, captured):
    """The router's own headers are recorded, including a fallback it chose itself."""
    _, body = captured
    body["payload"] = dict(OPENAI_REPLY, model="ignored-echo", id="body-id")
    body["headers"] = {
        "X-Agora-Model": "gpt-4o",
        "x-agora-provider": "openai",
        "x-agora-route": "resolved-route",
        "x-agora-request-id": "req-42",
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    monkeypatch.setenv("PRAXIS_LLM_MODEL", "claude-opus-5")
    monkeypatch.setenv("AGORA_ROUTE", "asked-for-route")

    client = llm.LLMClient()
    assert client.complete("hi") == "hello from openai"

    route = client.last_route
    assert route.routed_via_agora is True
    assert (route.requested_model, route.model) == ("claude-opus-5", "gpt-4o")
    assert route.fell_back is True
    assert (route.provider, route.route, route.request_id) == (
        "openai", "resolved-route", "req-42")
    described = client.route_description()
    assert "agora provider-router" in described
    assert "served gpt-4o (asked for claude-opus-5)" in described


def test_a_quiet_router_falls_back_to_the_response_body(monkeypatch, captured):
    """Nothing the router reports is required — a bare OpenAI reply still records."""
    _, body = captured
    body["payload"] = dict(OPENAI_REPLY, model="claude-opus-5", id="chatcmpl-7")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    monkeypatch.setenv("PRAXIS_LLM_MODEL", "claude-opus-5")

    client = llm.LLMClient()
    client.complete("hi")
    assert (client.last_route.model, client.last_route.request_id) == (
        "claude-opus-5", "chatcmpl-7")
    assert client.last_route.fell_back is False
    assert client.last_route.provider == ""


def test_the_routers_error_body_is_surfaced_and_the_router_is_named(monkeypatch):
    """A 502 from the router is the router's failure, with its own sentence first."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")

    def boom(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 502, "Bad Gateway",
            {"x-agora-provider": "anthropic", "x-agora-request-id": "req-9"},
            io.BytesIO(json.dumps(
                {"error": {"message": "every upstream for this route is rate limited"}}
            ).encode()),
        )

    monkeypatch.setattr(llm, "_urlopen", boom)
    with pytest.raises(llm.LLMError) as caught:
        llm.LLMClient().complete("hi")
    message = str(caught.value)
    assert "agora provider-router call failed (502)" in message
    assert "provider anthropic" in message and "request req-9" in message
    assert message.endswith("every upstream for this route is rate limited")


def test_an_unparseable_router_error_still_carries_its_body(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")

    def boom(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Server Error", {}, io.BytesIO(b"<html>nginx</html>")
        )

    monkeypatch.setattr(llm, "_urlopen", boom)
    with pytest.raises(llm.LLMError, match="<html>nginx</html>"):
        llm.LLMClient().complete("hi")


def test_an_unreachable_router_says_how_to_go_direct(monkeypatch):
    """agora is opt-in: a router that is down must not read as a provider outage."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")

    def boom(request, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(llm, "_urlopen", boom)
    with pytest.raises(llm.LLMError) as caught:
        llm.LLMClient().complete("hi")
    message = str(caught.value)
    assert "could not reach the agora provider-router" in message
    assert "unset AGORA_BASE_URL" in message


def test_describe_shows_the_route_a_human_would_need(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    monkeypatch.setenv("AGORA_ROUTE", "cheap-and-fast")
    monkeypatch.setenv("AGORA_FALLBACK_MODELS", "gpt-4o")

    described = llm.load_config().describe()
    assert "via agora provider-router at http://localhost:9000/v1/chat/completions" in described
    assert "route cheap-and-fast" in described
    assert "fallback gpt-4o" in described
    # Before any call, the client can only describe what was configured.
    assert llm.LLMClient().route_description() == described


def test_the_config_file_can_carry_the_router_hints(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {
        "provider": "openai", "api_key": "sk-file",
        "agora_base_url": "http://localhost:9000",
        "agora_route": "from-file",
        "agora_fallback_models": ["a-model", "b-model"],
    }}))
    monkeypatch.setenv("PRAXIS_CONFIG", str(path))
    config = llm.load_config()
    assert config.agora_route == "from-file"
    assert config.agora_fallbacks == ("a-model", "b-model")
    assert config.router_headers()[llm.AGORA_FALLBACK_HEADER] == "a-model,b-model"


# --- failure handling ----------------------------------------------------


def test_http_error_becomes_an_llm_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")

    def boom(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}')
        )

    monkeypatch.setattr(llm, "_urlopen", boom)
    with pytest.raises(llm.LLMError, match="401"):
        llm.LLMClient().complete("hi")


def test_unexpected_response_shape_becomes_an_llm_error(monkeypatch, captured):
    _, body = captured
    body["payload"] = {"nothing": "useful"}
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    with pytest.raises(llm.LLMError, match="unexpected response shape"):
        llm.LLMClient().complete("hi")


def test_no_api_key_is_committed_in_the_repo():
    """The anti-fabrication rule: keys come from env/config, never from source."""
    for path in [llm.__file__, *(str(p) for p in (ROOT / "praxis").glob("*.py"))]:
        text = Path(path).read_text()
        assert "sk-ant-" not in text and "sk-proj-" not in text
