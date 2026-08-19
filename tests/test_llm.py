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


# --- opt-in only: with AGORA_BASE_URL unset, this is what ships ----------
#
# The router is a deepening of one branch, never a rewrite of the client. These pin
# the other branch: the direct wire, per provider, exactly as it goes out today, so a
# future router change that leaks into a direct call fails here rather than in a user's
# BYO-key run. The literals were taken from `git show main:praxis/llm.py` driven
# through the same fixture, not from the current implementation's output.

DIRECT_WIRE = {
    "anthropic": {
        "env": {"ANTHROPIC_API_KEY": "sk-ant"},
        "url": "https://api.anthropic.com/v1/messages",
        "headers": {
            "content-type": "application/json",
            "x-api-key": "sk-ant",
            "anthropic-version": llm.ANTHROPIC_VERSION,
        },
        "json": {
            "model": "claude-opus-5",
            "max_tokens": 64,
            "system": "be brief",
            "messages": [{"role": "user", "content": "hi"}],
        },
        "reply": ANTHROPIC_REPLY,
        "text": "hello from anthropic",
        "describe": ("anthropic/claude-opus-5 via direct at "
                     "https://api.anthropic.com/v1/messages (timeout 120s)"),
    },
    "openai": {
        "env": {"OPENAI_API_KEY": "sk-oai"},
        "url": "https://api.openai.com/v1/chat/completions",
        "headers": {
            "content-type": "application/json",
            "authorization": "Bearer sk-oai",
        },
        "json": {
            "model": "gpt-4o",
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
        },
        "reply": OPENAI_REPLY,
        "text": "hello from openai",
        "describe": ("openai/gpt-4o via direct at "
                     "https://api.openai.com/v1/chat/completions (timeout 120s)"),
    },
    "local": {
        "env": {"PRAXIS_LLM_BASE_URL": "http://localhost:8000",
                "PRAXIS_LLM_MODEL": "qwen2.5-coder"},
        "url": "http://localhost:8000/v1/chat/completions",
        # No key at all: a local server is not asked for one, and none is invented.
        "headers": {"content-type": "application/json"},
        "json": {
            "model": "qwen2.5-coder",
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
        },
        "reply": OPENAI_REPLY,
        "text": "hello from openai",
        "describe": ("local/qwen2.5-coder via direct at "
                     "http://localhost:8000/v1/chat/completions (timeout 120s)"),
    },
}


def _apply(monkeypatch, env: dict) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("provider", sorted(DIRECT_WIRE))
def test_the_direct_wire_is_pinned_exactly_per_provider(monkeypatch, captured, provider):
    """Endpoint, wire format and auth, byte for byte — the whole request, not a subset."""
    expected = DIRECT_WIRE[provider]
    calls, body = captured
    body["payload"] = expected["reply"]
    _apply(monkeypatch, expected["env"])

    config = llm.load_config()
    assert config.provider == provider
    assert config.routed_via_agora is False
    # Nothing agora-shaped is resolved, so nothing agora-shaped can be sent.
    assert config.router_headers() == {}

    client = llm.LLMClient(config)
    assert client.complete("hi", system="be brief", max_tokens=64) == expected["text"]

    (call,) = calls
    assert call["url"] == expected["url"]
    assert call["headers"] == expected["headers"]
    assert call["json"] == expected["json"]
    assert call["timeout"] == llm.DEFAULT_TIMEOUT
    assert config.describe() == expected["describe"]
    # A direct call records only what it can know: there is no router to ask.
    assert client.last_route.routed_via_agora is False
    assert (client.last_route.provider, client.last_route.route,
            client.last_route.request_id) == ("", "", "")


def test_the_direct_failure_strings_are_pinned(monkeypatch):
    """The router's error surfacing must not have reworded a provider's failure."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    endpoint = "https://api.openai.com/v1/chat/completions"

    def refuse(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests",
            {"x-agora-provider": "openai"},  # a stray header changes nothing when direct
            io.BytesIO(json.dumps({"error": {"message": "slow down"}}).encode()),
        )

    monkeypatch.setattr(llm, "_urlopen", refuse)
    with pytest.raises(llm.LLMError) as caught:
        llm.LLMClient().complete("hi")
    assert str(caught.value) == (
        f'openai call failed (429) at {endpoint}: '
        '{"error": {"message": "slow down"}}'
    )

    def down(request, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(llm, "_urlopen", down)
    with pytest.raises(llm.LLMError) as caught:
        llm.LLMClient().complete("hi")
    # No mention of agora, and no advice about a variable the user never set.
    assert str(caught.value) == (
        f"could not reach {endpoint}: Connection refused"
    )


def test_one_env_resolves_both_modes_and_only_agora_adds(monkeypatch, captured):
    """agora on vs off from the SAME resolution: off is the pin above, on differs
    only in the router's own additions."""
    calls, body = captured
    base_env = {"ANTHROPIC_API_KEY": "sk-ant", "PRAXIS_LLM_MODEL": "claude-opus-5"}
    _apply(monkeypatch, base_env)

    off = llm.load_config()
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    on = llm.load_config()

    # Same provider, model, key and timeout — the router changes the route, not the
    # credentials or the subject of the call.
    assert (off.provider, off.model, off.api_key, off.timeout) == (
        on.provider, on.model, on.api_key, on.timeout)
    assert (off.routed_via_agora, on.routed_via_agora) == (False, True)
    assert off.endpoint == DIRECT_WIRE["anthropic"]["url"]
    assert on.endpoint == "http://localhost:9000/v1/chat/completions"
    assert (off.wire_format, on.wire_format) == ("messages", "chat")

    body["payload"] = ANTHROPIC_REPLY
    assert llm.LLMClient(off).complete("hi") == "hello from anthropic"
    body["payload"] = OPENAI_REPLY
    assert llm.LLMClient(on).complete("hi") == "hello from openai"
    direct, routed = calls
    assert direct["headers"] == {"content-type": "application/json",
                                 "x-api-key": "sk-ant",
                                 "anthropic-version": llm.ANTHROPIC_VERSION}
    assert routed["headers"] == {"content-type": "application/json",
                                 "authorization": "Bearer sk-ant"}
    # Both send the same three keys; only where they go and how they are framed differ.
    assert set(direct["json"]) == set(routed["json"]) == {"model", "max_tokens", "messages"}
    assert direct["json"]["model"] == routed["json"]["model"] == "claude-opus-5"


def test_agora_hints_without_a_base_url_leave_the_direct_call_identical(monkeypatch, captured):
    """A leftover AGORA_ROUTE/AGORA_API_KEY in a shell must not reach a provider."""
    calls, body = captured
    body["payload"] = ANTHROPIC_REPLY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

    llm.LLMClient().complete("hi", system="be brief", max_tokens=64)
    clean_call, clean_describe = calls[0], llm.load_config().describe()

    for name, value in (("AGORA_API_KEY", "sk-agora"),
                        ("AGORA_ROUTE", "cheap-and-fast"),
                        ("AGORA_FALLBACK_MODELS", "gpt-4o,claude-opus-5")):
        monkeypatch.setenv(name, value)

    config = llm.load_config()
    # They resolve — they are simply never honoured without a router to honour them.
    assert config.agora_route == "cheap-and-fast"
    assert config.agora_fallbacks == ("gpt-4o", "claude-opus-5")
    assert config.routed_via_agora is False
    assert config.router_headers() == {}
    assert config.api_key == "sk-ant"  # AGORA_API_KEY does not take over a direct call

    llm.LLMClient(config).complete("hi", system="be brief", max_tokens=64)
    assert calls[1] == clean_call
    assert config.describe() == clean_describe == DIRECT_WIRE["anthropic"]["describe"]


def test_building_a_client_reaches_nothing(monkeypatch, captured):
    """No probe, no handshake, no discovery call — in either mode. The first byte on
    the wire is the caller's own prompt, so agora being down cannot break startup."""
    calls, _ = captured
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert llm.LLMClient().last_route is None
    monkeypatch.setenv("AGORA_BASE_URL", "http://localhost:9000")
    client = llm.LLMClient()
    assert client.last_route is None
    assert client.route_description() == client.config.describe()
    assert calls == []


def test_no_module_imports_agora():
    """The hard-dependency check: agora is a URL in an env var, never an import."""
    sources = [
        *(ROOT / "praxis").rglob("*.py"),
        *(ROOT / "launcher").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
        *ROOT.glob("*.py"),
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in sources
        if any(line.startswith(("import agora", "from agora"))
               for line in (raw.strip() for raw in path.read_text().splitlines()))
    ]
    assert offenders == []


def test_agora_is_in_no_manifest():
    """`AGORA_BASE_URL` is consumed by reference: nothing declares agora a dependency."""
    for name in ("pyproject.toml", "ui/package.json", "src-tauri/Cargo.toml"):
        path = ROOT / name
        if path.is_file():
            assert "agora" not in path.read_text().lower(), name


def test_the_llm_module_needs_no_agora_environment():
    """Importing and resolving with a completely bare environment still works — the
    only module that knows the router's name never assumes it is there."""
    config = llm.load_config(env={"OPENAI_API_KEY": "sk-oai"}, config_path=None)
    assert config.routed_via_agora is False
    assert config.endpoint == DIRECT_WIRE["openai"]["url"]
    assert config.describe() == DIRECT_WIRE["openai"]["describe"]
