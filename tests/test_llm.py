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
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in LEAKY:
        monkeypatch.delenv(name, raising=False)
    # Never read the developer's real ~/.config/praxis/config.json.
    monkeypatch.setattr(llm, "default_config_path", lambda: tmp_path / "missing.json")


class _Response(io.BytesIO):
    """Just enough of an http response for `with _urlopen(...) as r: r.read()`."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def captured(monkeypatch):
    """Mock the network; record the request and reply with a canned body."""
    calls: list[dict] = []
    body = {"payload": None}

    def fake_urlopen(request, timeout):
        calls.append(
            {
                "url": request.full_url,
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "json": json.loads(request.data),
                "timeout": timeout,
            }
        )
        return _Response(json.dumps(body["payload"]).encode())

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
