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

The agora path is opt-in and stays that way: with AGORA_BASE_URL unset nothing below
runs, no module here imports or reaches agora, and the direct calls are exactly what
they were before the router existed. What the router adds when it *is* set:

  * routing hints ride in `x-agora-*` **headers**, never in the JSON body — a body key
    the upstream model does not know is a 400, a header it does not know is ignored, so
    AGORA_ROUTE / AGORA_FALLBACK_MODELS can never make a payload a provider rejects;
  * what the router actually served is read back off the reply (`model`/`id`, plus any
    `x-agora-*` headers) into `LLMClient.last_route`, so a fallback the router chose is
    visible rather than silent — read defensively, since none of it is guaranteed;
  * a router failure is reported as the router's, with the router's own message pulled
    out of its error body the way a provider's already is.

The transport is the standard library's: `_urlopen` is the one network seam, and
mocking it is all a test has to do. What wraps it is a retry loop, because a 429 or a
5xx is the provider asking us to wait rather than the call being wrong, and absorbing
it here is what keeps the repair loops in construct.py / checks.py spending their
attempts on the *grader* (see RetryPolicy):

  retried    429, any 5xx (Anthropic's 529 `overloaded_error` among them), and any
             connection-level failure (refused, reset, socket timeout)
  not        every other 4xx, a non-JSON body, an unexpected shape, a config error —
             each fails on the first attempt, with no wait
  how long   `Retry-After` when the server sends one (both RFC 9110 forms), else
             exponential backoff from RETRY_BASE_DELAY, doubling, capped at
             RETRY_MAX_DELAY, plus up to RETRY_JITTER seconds of jitter; bounded by
             DEFAULT_RETRY_ATTEMPTS attempts and DEFAULT_RETRY_BUDGET seconds total

tenacity drives that loop (the one non-stdlib import here); every attempt sends a
byte-identical request, and exhausting the retries raises exactly the LLMError a single
failure raises, so the frozen direct wire and its pinned error strings are untouched.

Env vars, all optional but at least one key needed for a direct provider:

  PRAXIS_LLM_PROVIDER   anthropic | openai | local  (else inferred from which key is set)
  PRAXIS_LLM_MODEL      overrides the per-provider default
  PRAXIS_LLM_API_KEY    overrides ANTHROPIC_API_KEY / OPENAI_API_KEY
  PRAXIS_LLM_BASE_URL   overrides the provider endpoint (also selects `local` on its own)
  PRAXIS_LLM_TIMEOUT    seconds to wait for one reply (default 120; raise it for a slow
                        local model — constructing a notebook is a long single reply)
  PRAXIS_LLM_RETRY_ATTEMPTS  attempts per call, the first one included (default 4)
  PRAXIS_LLM_RETRY_BUDGET    seconds one call may take in total, sleeps included
                             (default 45; a bad value in either is an error, not a
                             silent fallback, exactly like PRAXIS_LLM_TIMEOUT)
  ANTHROPIC_API_KEY / OPENAI_API_KEY
  AGORA_BASE_URL        set -> route through agora; unset -> go direct
  AGORA_API_KEY         key for the router (falls back to the provider key)
  AGORA_ROUTE           named route/profile to ask the router for (agora only)
  AGORA_FALLBACK_MODELS comma-separated models the router may fall back to (agora only)
  PRAXIS_CONFIG         path to the JSON config file
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from tenacity import RetryCallState, Retrying, retry_if_exception

PROVIDERS = ("anthropic", "openai", "local")

# The Messages API version Praxis pins for direct Anthropic calls.
ANTHROPIC_VERSION = "2023-06-01"

# Generous by default: on current Anthropic models thinking is on by default and
# max_tokens caps thinking *plus* the reply, so a tight cap truncates mid-answer.
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT = 120.0

# The retry policy's defaults, all overridable per client (see RetryPolicy) and the
# first two from the environment. The budget is sized for the *interactive* caller:
# launcher/app.py grades a `short` answer through this client inside an HTTP request,
# so a call that keeps being rate-limited has to give up while someone is still
# watching, rather than hold a connection open for the per-attempt timeout times four.
DEFAULT_RETRY_ATTEMPTS = 4      # the first call plus three retries
DEFAULT_RETRY_BUDGET = 45.0     # seconds for the whole call, sleeps and requests alike
RETRY_BASE_DELAY = 1.0          # the first backoff wait, doubling from there
RETRY_MAX_DELAY = 16.0          # cap on any one wait, before jitter
RETRY_JITTER = 0.5              # up to this many seconds added, so retries de-sync

# Retried on their own; every 5xx is retried too (529 included), and a failure with no
# HTTP status at all — a refused connection, a reset, a socket timeout — reads as 0.
RETRYABLE_STATUS = (429, 0)

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

# The router's own vocabulary, used on the agora path only. Praxis consumes agora's
# contract by reference rather than re-stating it: everything here is a *hint* going
# out and a *best effort* coming back, so a router that ignores or omits any of it
# still works exactly like the plain base-URL swap that shipped before.
AGORA_ROUTE_HEADER = "x-agora-route"
AGORA_FALLBACK_HEADER = "x-agora-fallback"

# Read back off the reply, first match wins; absent means "the router didn't say".
AGORA_SERVED_MODEL_HEADERS = ("x-agora-model", "x-agora-served-model")
AGORA_PROVIDER_HEADERS = ("x-agora-provider", "x-agora-upstream")
AGORA_ROUTE_HEADERS = ("x-agora-route", "x-agora-selected-route")
AGORA_REQUEST_ID_HEADERS = ("x-agora-request-id", "x-request-id")


class LLMError(RuntimeError):
    """A call to the provider failed.

    The message is the whole contract for a caller that only prints it, and it is
    pinned per provider by tests/test_llm.py. Everything the retry loop needs to
    decide what to do next therefore rides as attributes, never as extra words:
    exhausting four attempts must read exactly like failing once.
    """

    #: The HTTP status behind the failure — 0 when the call never got one (refused,
    #: reset, timed out), None when the provider answered and its answer was the
    #: problem (a non-JSON body, an unexpected shape).
    status: int | None = None
    #: Seconds the server asked us to wait, when it said so (RFC 9110 `Retry-After`).
    retry_after: float | None = None
    #: How many attempts were spent getting here.
    attempts: int = 1


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


def _header_map(source: object) -> dict[str, str]:
    """Headers as a lowercase dict — anything unusable reads as "none given".

    Deliberately forgiving: nothing the router reports is required for a call to
    succeed, and a response object without headers at all (a stub, a proxy that
    strips them) must behave like a router that simply stayed quiet.
    """
    items = getattr(source, "items", None)
    if items is None:
        return {}
    try:
        return {str(k).lower(): str(v).strip() for k, v in items()}
    except (AttributeError, TypeError, ValueError):
        return {}


def _first_header(headers: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = headers.get(name, "").strip()
        if value:
            return value
    return ""


def _error_message(body: str) -> str:
    """The message out of an OpenAI-shaped error body, or "" if it isn't one.

    The router reports an upstream failure in its own body; pulling the sentence out
    of it is what makes `error.message` reach the UI instead of a wall of JSON.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "detail", "description"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    for value in (error, data.get("message"), data.get("detail")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@dataclass(frozen=True)
class RouteReport:
    """What actually served one call — the router's answer, not our request.

    Recorded for every call so a caller needs no branch, but only the agora path can
    fill in more than the endpoint: a direct call has no router to ask.
    """

    endpoint: str
    routed_via_agora: bool
    requested_model: str
    model: str = ""          # what the router says it served
    provider: str = ""       # which upstream it picked
    route: str = ""          # which named route it resolved to
    request_id: str = ""     # the router's id for this call, for its own logs

    @property
    def fell_back(self) -> bool:
        """The router served something other than what was asked for."""
        return bool(self.model) and self.model != self.requested_model

    def describe(self) -> str:
        if not self.routed_via_agora:
            return f"{self.requested_model} direct at {self.endpoint}"
        parts = [f"served {self.model or 'unreported'}"]
        if self.fell_back:
            parts[0] += f" (asked for {self.requested_model})"
        if self.provider:
            parts.append(f"provider {self.provider}")
        if self.route:
            parts.append(f"route {self.route}")
        if self.request_id:
            parts.append(f"request {self.request_id}")
        return f"agora provider-router at {self.endpoint}: " + ", ".join(parts)


@dataclass(frozen=True)
class LLMConfig:
    """Everything needed to make one call, with no secrets on disk in this repo."""

    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    agora_base_url: str = ""
    # Router hints. Both are ignored unless agora_base_url is set — there is no router
    # to honour them otherwise, and the direct payload must not change shape.
    agora_route: str = ""
    agora_fallbacks: tuple[str, ...] = ()
    # Seconds to wait for one reply. A local server generating a 9000-character
    # notebook is minutes, not seconds, of work, so this has to be raisable from
    # outside — the default is sized for a hosted provider.
    timeout: float = DEFAULT_TIMEOUT
    # The two halves of the retry budget. Settable for the same reason the timeout is:
    # what a hosted provider's rate limiter needs and what a local server needs differ.
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_budget: float = DEFAULT_RETRY_BUDGET

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

    def router_headers(self) -> dict[str, str]:
        """The routing hints for one call — empty for every direct call.

        Headers, never body keys: the router reads these, and anything that doesn't
        understand them (including the upstream model, which never sees them) ignores
        them. That is what keeps a route or a fallback list from ever becoming a
        parameter a provider rejects.
        """
        if not self.routed_via_agora:
            return {}
        headers = {}
        if self.agora_route:
            headers[AGORA_ROUTE_HEADER] = self.agora_route
        if self.agora_fallbacks:
            headers[AGORA_FALLBACK_HEADER] = ",".join(self.agora_fallbacks)
        return headers

    def describe(self) -> str:
        route = "agora provider-router" if self.routed_via_agora else "direct"
        detail = ""
        if self.routed_via_agora:
            if self.agora_route:
                detail += f" route {self.agora_route}"
            if self.agora_fallbacks:
                detail += f" fallback {' -> '.join(self.agora_fallbacks)}"
        return (f"{self.provider}/{self.model} via {route} at {self.endpoint}{detail} "
                f"(timeout {self.timeout:g}s)")


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


def _resolve_timeout(raw: str) -> float:
    """`PRAXIS_LLM_TIMEOUT` in seconds, or the default. A bad value is an error, not
    a silent fallback — a run that then dies two minutes in is unexplainable."""
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        timeout = float(raw)
    except ValueError:
        raise LLMConfigError(f"PRAXIS_LLM_TIMEOUT must be a number of seconds, not {raw!r}") from None
    if timeout <= 0:
        raise LLMConfigError(f"PRAXIS_LLM_TIMEOUT must be positive, not {timeout}")
    return timeout


def _resolve_number(raw: str, name: str, default: float, integral: bool = False) -> float:
    """A positive number from the environment, or the default. Same rule as the
    timeout's: a bad value is an error, because silently ignoring it means the retry
    policy a user thought they set was never the one that ran."""
    if not raw:
        return default
    try:
        value = int(raw) if integral else float(raw)
    except ValueError:
        unit = "a whole number of attempts" if integral else "a number of seconds"
        raise LLMConfigError(f"{name} must be {unit}, not {raw!r}") from None
    if value <= 0:
        raise LLMConfigError(f"{name} must be positive, not {value}")
    return value


def _resolve_fallbacks(env: dict, file_cfg: dict) -> tuple[str, ...]:
    """`AGORA_FALLBACK_MODELS` as a comma-separated string, or a JSON list in the file."""
    raw = env.get("AGORA_FALLBACK_MODELS") or file_cfg.get("agora_fallback_models") or ""
    parts = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return tuple(item for item in (str(p).strip() for p in parts) if item)


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
    # Resolved either way, honoured only when there is a router: an AGORA_* value left
    # in the environment must not change a direct call.
    agora_route = _pick(env, file_cfg, "AGORA_ROUTE", "agora_route")
    agora_fallbacks = _resolve_fallbacks(env, file_cfg)

    timeout = _resolve_timeout(_pick(env, file_cfg, "PRAXIS_LLM_TIMEOUT", "timeout"))
    retry_attempts = int(_resolve_number(
        _pick(env, file_cfg, "PRAXIS_LLM_RETRY_ATTEMPTS", "retry_attempts"),
        "PRAXIS_LLM_RETRY_ATTEMPTS", DEFAULT_RETRY_ATTEMPTS, integral=True))
    retry_budget = _resolve_number(
        _pick(env, file_cfg, "PRAXIS_LLM_RETRY_BUDGET", "retry_budget"),
        "PRAXIS_LLM_RETRY_BUDGET", DEFAULT_RETRY_BUDGET)

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
        agora_route=agora_route,
        agora_fallbacks=agora_fallbacks,
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_budget=retry_budget,
    )


def _urlopen(request: urllib.request.Request, timeout: float):
    """The single network seam — tests replace this, nothing else."""
    return urllib.request.urlopen(request, timeout=timeout)


def _sleep(seconds: float) -> None:
    """The single wait seam. Replaced wholesale in the suite: nothing sleeps for real."""
    time.sleep(seconds)


def _retry_after(headers: dict[str, str], now: float) -> float | None:
    """`Retry-After` as seconds from `now`, in either RFC 9110 form.

    delta-seconds (`Retry-After: 2`) and HTTP-date (`Retry-After: <IMF-fixdate>`) are
    both honoured; a date already past means "no extra wait", and anything unparseable
    means the server said nothing usable, so the backoff schedule decides instead.
    """
    raw = headers.get("retry-after", "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:  # an HTTP-date without a zone is GMT by definition
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, when.timestamp() - now)


def _is_transient(exc: BaseException) -> bool:
    """Worth another attempt? Only a rate limit, a server-side failure or no answer."""
    if not isinstance(exc, LLMError) or isinstance(exc, LLMConfigError):
        return False
    status = exc.status
    if status is None:
        return False
    return status in RETRYABLE_STATUS or 500 <= status < 600


@dataclass(frozen=True)
class RetryPolicy:
    """How hard one `complete()` tries, and on whose clock.

    The numbers come from the config (so two of them are env-settable); the four
    callables are the seams the tests inject — a fake clock that only moves when the
    fake sleep is called is what lets a backoff schedule be asserted exactly, with no
    test waiting on a real second. `None` means "the module's own seam", read at call
    time so a monkeypatched `_sleep` still reaches a default policy.
    """

    attempts: int = DEFAULT_RETRY_ATTEMPTS
    budget: float = DEFAULT_RETRY_BUDGET
    base: float = RETRY_BASE_DELAY
    cap: float = RETRY_MAX_DELAY
    jitter: float = RETRY_JITTER
    sleep: Callable[[float], None] | None = None
    monotonic: Callable[[], float] | None = None
    wallclock: Callable[[], float] | None = None
    rng: Callable[[], float] | None = None

    def pause(self, seconds: float) -> None:
        (self.sleep or _sleep)(max(0.0, seconds))

    def now(self) -> float:
        """Elapsed-time clock, for the budget."""
        return (self.monotonic or time.monotonic)()

    def wall(self) -> float:
        """Wall clock, for an HTTP-date `Retry-After`."""
        return (self.wallclock or time.time)()

    def noise(self) -> float:
        return self.jitter * (self.rng or random.random)()

    def backoff(self, retries: int) -> float:
        """The wait before attempt `retries + 1`, when the server named no delay."""
        return min(self.base * (2 ** max(0, retries - 1)), self.cap) + self.noise()


class LLMClient:
    """A minimal chat client over whichever provider the environment selected."""

    def __init__(self, config: LLMConfig | None = None, timeout: float | None = None,
                 retry: RetryPolicy | None = None):
        self.config = config or load_config()
        # An explicit argument wins; otherwise follow the resolved config, so
        # PRAXIS_LLM_TIMEOUT reaches every caller without one of them plumbing it.
        self.timeout = self.config.timeout if timeout is None else timeout
        # Same rule for the retry budget, and the same reason: no caller plumbs it.
        self.retry = retry or RetryPolicy(
            attempts=self.config.retry_attempts, budget=self.config.retry_budget)
        # What served the most recent call. None until one has been made.
        self.last_route: RouteReport | None = None

    # -- request building ------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.config.wire_format == "messages":
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        elif self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        # Empty unless a router is in the path, so a direct request is unchanged.
        headers.update(self.config.router_headers())
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
        """Send one prompt and return the model's text, retrying transient failures.

        The retry lives here, under the callers rather than in them: a 429 absorbed
        by the transport costs a wait, while one that reached construct.py costs a
        repair attempt — an attempt that exists to answer the grader, not the network.
        Every attempt is the same bytes, and the failure that finally escapes is the
        one a single attempt would have raised (with `.attempts` on it saying how many
        there were), so nothing downstream has to learn a new string.
        """
        body = json.dumps(self._payload(prompt, system, max_tokens)).encode()
        headers = self._headers()
        policy = self.retry
        started = policy.now()

        def wait(state: RetryCallState) -> float:
            asked = getattr(state.outcome.exception(), "retry_after", None)
            # Jitter rides on the server's figure too: a rate limiter that hands the
            # same delta-seconds to every client would otherwise re-synchronise them.
            return policy.backoff(state.attempt_number) if asked is None \
                else asked + policy.noise()

        def stop(state: RetryCallState) -> bool:
            # tenacity computes the wait before asking this, so a `Retry-After` longer
            # than what is left of the budget ends the call now instead of sleeping
            # past it — the caller gets the provider's own error, on time.
            if state.attempt_number >= policy.attempts:
                return True
            return (policy.now() - started) + state.upcoming_sleep > policy.budget

        for attempt in Retrying(retry=retry_if_exception(_is_transient), wait=wait,
                                stop=stop, sleep=policy.pause, reraise=True):
            with attempt:
                return self._attempt(body, headers, attempt.retry_state.attempt_number)
        raise AssertionError("unreachable: Retrying either returns or raises")

    def _attempt(self, body: bytes, headers: dict[str, str], number: int) -> str:
        """One request. Every failure carries the status the retry loop reads."""
        request = urllib.request.Request(
            self.config.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with _urlopen(request, self.timeout) as response:
                raw = response.read()
                reply_headers = _header_map(getattr(response, "headers", None))
        except urllib.error.HTTPError as exc:  # 4xx/5xx carry a useful body
            detail = exc.read().decode("utf-8", "replace")[:500] if exc.fp else ""
            raise self._failed(
                self._http_failure(exc, detail), number, status=exc.code,
                retry_after=_retry_after(
                    _header_map(getattr(exc, "headers", None)), self.retry.wall()),
            ) from exc
        except urllib.error.URLError as exc:
            raise self._failed(self._unreachable(exc.reason), number, status=0) from exc

        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise self._failed(
                f"non-JSON response from {self.config.endpoint}", number) from exc
        self.last_route = self._route_report(data, reply_headers)
        return self._text(data, number)

    def _failed(self, message: str, attempts: int, *, status: int | None = None,
                retry_after: float | None = None) -> LLMError:
        """An LLMError with the retry loop's facts attached, never spelled out in it."""
        error = LLMError(message)
        error.status = status
        error.retry_after = retry_after
        error.attempts = attempts
        return error

    # -- what came back --------------------------------------------------

    def _route_report(self, data: object, headers: dict[str, str]) -> RouteReport:
        """Record what served the call. The router's headers win over the body's
        `model`, which some routers echo back unchanged from the request."""
        body = data if isinstance(data, dict) else {}
        if not self.config.routed_via_agora:
            return RouteReport(
                endpoint=self.config.endpoint,
                routed_via_agora=False,
                requested_model=self.config.model,
                model=str(body.get("model") or ""),
            )
        served = _first_header(headers, AGORA_SERVED_MODEL_HEADERS)
        return RouteReport(
            endpoint=self.config.endpoint,
            routed_via_agora=True,
            requested_model=self.config.model,
            model=served or str(body.get("model") or ""),
            provider=_first_header(headers, AGORA_PROVIDER_HEADERS),
            route=_first_header(headers, AGORA_ROUTE_HEADERS) or self.config.agora_route,
            request_id=_first_header(headers, AGORA_REQUEST_ID_HEADERS)
            or str(body.get("id") or ""),
        )

    def route_description(self) -> str:
        """The route in use, as specifically as it is known — what the router reported
        after a call, and what was configured before one."""
        return self.last_route.describe() if self.last_route else self.config.describe()

    # -- when it fails ---------------------------------------------------

    def _http_failure(self, exc: urllib.error.HTTPError, detail: str) -> str:
        if not self.config.routed_via_agora:
            return (f"{self.config.provider} call failed ({exc.code}) at "
                    f"{self.config.endpoint}: {detail}")
        # A router failure is the *router's*, and it knows more about it than we do:
        # name it, say which upstream it had picked, and lead with its own sentence
        # rather than burying it in the raw body (which still follows if there is none).
        headers = _header_map(getattr(exc, "headers", None))
        facts = [f"provider {p}" for p in [_first_header(headers, AGORA_PROVIDER_HEADERS)] if p]
        facts += [f"route {r}" for r in
                  [_first_header(headers, AGORA_ROUTE_HEADERS) or self.config.agora_route] if r]
        facts += [f"request {i}" for i in [_first_header(headers, AGORA_REQUEST_ID_HEADERS)] if i]
        where = f" [{', '.join(facts)}]" if facts else ""
        return (f"agora provider-router call failed ({exc.code}) for "
                f"{self.config.provider}/{self.config.model} at {self.config.endpoint}"
                f"{where}: {_error_message(detail) or detail}")

    def _unreachable(self, reason: object) -> str:
        if not self.config.routed_via_agora:
            return f"could not reach {self.config.endpoint}: {reason}"
        # The router being down must never read as the provider being down, and the
        # way out is one unset variable away — agora is opt-in, so say so here.
        return (f"could not reach the agora provider-router at {self.config.endpoint}: "
                f"{reason} (unset AGORA_BASE_URL to call {self.config.provider} directly)")

    def _text(self, data: dict, attempts: int = 1) -> str:
        try:
            if self.config.wire_format == "messages":
                blocks = data["content"]
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise self._failed(
                f"unexpected response shape from {self.config.endpoint}: "
                f"{json.dumps(data)[:300]}", attempts
            ) from exc


if __name__ == "__main__":  # a doctor: prove the env resolves without spending a token
    try:
        print(load_config().describe())
    except LLMConfigError as exc:
        raise SystemExit(f"praxis.llm: {exc}")
