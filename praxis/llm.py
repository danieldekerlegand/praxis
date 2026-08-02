#!/usr/bin/env python3
"""Bring-your-own-key LLM access for the Praxis construction core.

Praxis never ships a key. Provider, key, model and endpoint are resolved from the
environment first, then from a JSON config file (`$PRAXIS_CONFIG`, else
`~/.config/praxis/config.json`). Nothing is ever read from source.

Four routing modes, three of them direct:

  anthropic  POST <base>/v1/messages         headers: x-api-key + anthropic-version
  openai     POST <base>/v1/chat/completions headers: Authorization: Bearer
  local      same wire format as openai, against an OpenAI-compatible server you run
             (Ollama, LM Studio, llama.cpp, vLLM, ...)
  agora      when AGORA_BASE_URL is set, every call goes to agora's provider-router
             instead of the provider's own endpoint. The router speaks the
             OpenAI-compatible chat-completions format; the model string is passed
             through untouched, so set PRAXIS_LLM_MODEL to whatever the router expects.

Only the standard library is used, so the construction core stays dependency-light
(see pyproject: `nbformat` is the sole hard dependency) and the tests have exactly one
seam to mock: `_urlopen`.

Env vars, all optional but at least one key needed for a direct provider:

  PRAXIS_LLM_PROVIDER   anthropic | openai | local  (else inferred from which key is set)
  PRAXIS_LLM_MODEL      overrides the per-provider default
  PRAXIS_LLM_API_KEY    overrides ANTHROPIC_API_KEY / OPENAI_API_KEY
  PRAXIS_LLM_BASE_URL   overrides the provider endpoint (also selects `local` on its own)
  ANTHROPIC_API_KEY / OPENAI_API_KEY
  AGORA_BASE_URL        set -> route through agora; unset -> go direct
  AGORA_API_KEY         key for the router (falls back to the provider key)
  PRAXIS_CONFIG         path to the JSON config file
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROVIDERS = ("anthropic", "openai", "local")

# The Messages API version Praxis pins for direct Anthropic calls.
ANTHROPIC_VERSION = "2023-06-01"

# Generous by default: on current Anthropic models thinking is on by default and
# max_tokens caps thinking *plus* the reply, so a tight cap truncates mid-answer.
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT = 120.0

DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "local": "http://localhost:11434",
}

DEFAULT_MODEL = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-4o",
    # OpenAI-compatible servers ignore or alias this; override with PRAXIS_LLM_MODEL.
    "local": "local-model",
}

PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "local": "PRAXIS_LLM_API_KEY",
}


class LLMError(RuntimeError):
    """A call to the provider failed."""


class LLMConfigError(LLMError):
    """Provider/key/model could not be resolved from the environment or config."""


def default_config_path() -> Path:
    return Path(os.path.expanduser("~")) / ".config" / "praxis" / "config.json"


def _normalize_base(url: str) -> str:
    """Strip a trailing slash and a trailing `/v1` so callers can pass either form."""
    url = url.strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


@dataclass(frozen=True)
class LLMConfig:
    """Everything needed to make one call, with no secrets on disk in this repo."""

    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    agora_base_url: str = ""

    @property
    def routed_via_agora(self) -> bool:
        return bool(self.agora_base_url)

    @property
    def endpoint(self) -> str:
        if self.routed_via_agora:
            return f"{_normalize_base(self.agora_base_url)}/v1/chat/completions"
        base = _normalize_base(self.base_url or DEFAULT_BASE_URL[self.provider])
        if self.provider == "anthropic":
            return f"{base}/v1/messages"
        return f"{base}/v1/chat/completions"

    @property
    def wire_format(self) -> str:
        """`messages` (Anthropic) or `chat` (OpenAI-compatible, incl. agora)."""
        if self.provider == "anthropic" and not self.routed_via_agora:
            return "messages"
        return "chat"

    def describe(self) -> str:
        route = "agora provider-router" if self.routed_via_agora else "direct"
        return f"{self.provider}/{self.model} via {route} at {self.endpoint}"


def _read_config_file(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise LLMConfigError(f"could not read LLM config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMConfigError(f"LLM config {path} must hold a JSON object")
    # Allow the LLM settings to be nested under "llm" so the file can grow later.
    section = data.get("llm")
    return section if isinstance(section, dict) else data


def _pick(env: dict, file_cfg: dict, env_name: str, file_key: str) -> str:
    """Env wins over the config file; both are optional."""
    return str(env.get(env_name) or file_cfg.get(file_key) or "").strip()


def _resolve_provider(env: dict, file_cfg: dict) -> str:
    provider = _pick(env, file_cfg, "PRAXIS_LLM_PROVIDER", "provider").lower()
    if provider:
        if provider not in PROVIDERS:
            raise LLMConfigError(
                f"unknown provider {provider!r}; expected one of {', '.join(PROVIDERS)}"
            )
        return provider
    # No explicit choice: infer from whichever credential/endpoint is present.
    for candidate in ("anthropic", "openai"):
        if env.get(PROVIDER_KEY_ENV[candidate]):
            return candidate
    if _pick(env, file_cfg, "PRAXIS_LLM_BASE_URL", "base_url"):
        return "local"
    raise LLMConfigError(
        "no LLM provider configured — set PRAXIS_LLM_PROVIDER, or one of "
        "ANTHROPIC_API_KEY / OPENAI_API_KEY, or PRAXIS_LLM_BASE_URL for a local "
        f"OpenAI-compatible server (config file: {default_config_path()})"
    )


def load_config(env: dict | None = None, config_path: str | Path | None = None) -> LLMConfig:
    """Resolve a config from env + config file. Raises LLMConfigError if it can't."""
    env = dict(os.environ if env is None else env)
    if config_path is None:
        config_path = env.get("PRAXIS_CONFIG") or default_config_path()
    file_cfg = _read_config_file(Path(config_path))

    provider = _resolve_provider(env, file_cfg)
    model = _pick(env, file_cfg, "PRAXIS_LLM_MODEL", "model") or DEFAULT_MODEL[provider]
    base_url = _pick(env, file_cfg, "PRAXIS_LLM_BASE_URL", "base_url")
    agora_base_url = _pick(env, file_cfg, "AGORA_BASE_URL", "agora_base_url")

    api_key = _pick(env, file_cfg, "PRAXIS_LLM_API_KEY", "api_key")
    if not api_key:
        api_key = str(env.get(PROVIDER_KEY_ENV[provider]) or "").strip()
    if agora_base_url:
        api_key = _pick(env, file_cfg, "AGORA_API_KEY", "agora_api_key") or api_key
    elif provider != "local" and not api_key:
        raise LLMConfigError(
            f"no API key for provider {provider!r} — set {PROVIDER_KEY_ENV[provider]} "
            "or PRAXIS_LLM_API_KEY (never commit a key)"
        )

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        agora_base_url=agora_base_url,
    )


def _urlopen(request: urllib.request.Request, timeout: float):
    """The single network seam — tests replace this, nothing else."""
    return urllib.request.urlopen(request, timeout=timeout)


class LLMClient:
    """A minimal chat client over whichever provider the environment selected."""

    def __init__(self, config: LLMConfig | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.config = config or load_config()
        self.timeout = timeout

    # -- request building ------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.config.wire_format == "messages":
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        elif self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _payload(self, prompt: str, system: str | None, max_tokens: int) -> dict:
        if self.config.wire_format == "messages":
            payload = {
                "model": self.config.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                payload["system"] = system
            return payload
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        return {"model": self.config.model, "max_tokens": max_tokens, "messages": messages}

    # -- the call --------------------------------------------------------

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send one prompt and return the model's text."""
        body = json.dumps(self._payload(prompt, system, max_tokens)).encode()
        request = urllib.request.Request(
            self.config.endpoint, data=body, headers=self._headers(), method="POST"
        )
        try:
            with _urlopen(request, self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:  # 4xx/5xx carry a useful body
            detail = exc.read().decode("utf-8", "replace")[:500] if exc.fp else ""
            raise LLMError(
                f"{self.config.provider} call failed ({exc.code}) at "
                f"{self.config.endpoint}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"could not reach {self.config.endpoint}: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise LLMError(f"non-JSON response from {self.config.endpoint}") from exc
        return self._text(data)

    def _text(self, data: dict) -> str:
        try:
            if self.config.wire_format == "messages":
                blocks = data["content"]
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"unexpected response shape from {self.config.endpoint}: "
                f"{json.dumps(data)[:300]}"
            ) from exc


if __name__ == "__main__":  # a doctor: prove the env resolves without spending a token
    try:
        print(load_config().describe())
    except LLMConfigError as exc:
        raise SystemExit(f"praxis.llm: {exc}")
