"""A tiny OpenAI-compatible model endpoint, so the retry policy can be tested for real.

`praxis/llm.py`'s retry decisions are made from what comes back over HTTP: a status, a
`Retry-After` header, or nothing at all because the host refused the connection. Faking
that at the Python level — raising `urllib.error.HTTPError` from a patched `_urlopen`,
as most of tests/test_llm.py does — proves the branch but not the reading: a header set
here is a header urllib parsed, and a body served here is a body the client decoded.

So this serves a scripted sequence on a loopback port, in the style of `tests/mocks3.py`
and `tests/mockdav.py`:

* **Replies are a queue, and the last one repeats.** `MockLLM(rate_limited(), ok())` is
  "fail once then succeed"; `MockLLM(rate_limited())` is a provider that never lets up,
  which is what a budget has to survive.
* **Every request is recorded** — path, headers and decoded JSON body — so a test can
  assert that four attempts sent four byte-identical requests, not just that there were
  four of them.
* **Nothing here sleeps or retries.** The waits belong to the client, on the fake clock
  the test injects; this end only ever answers immediately.

It speaks the chat-completions format, which is what both the direct openai/local branch
and the agora branch send, so one stub serves both.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: The shape an OpenAI-compatible server returns; `text` is what `complete()` yields.
OK_BODY = {"choices": [{"message": {"content": "hello from the stub"}}]}


@dataclass
class Reply:
    """One scripted answer: a status, a body and whatever headers the case needs."""

    status: int = 200
    body: object = field(default_factory=lambda: OK_BODY)
    headers: dict[str, str] = field(default_factory=dict)

    def encoded(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        if isinstance(self.body, str):
            return self.body.encode()
        return json.dumps(self.body).encode()


def ok(text: str = "hello from the stub", **headers: str) -> Reply:
    return Reply(200, {"choices": [{"message": {"content": text}}]}, dict(headers))


def rate_limited(retry_after: str | None = None) -> Reply:
    """A 429, optionally naming a delay in either of RFC 9110's two forms."""
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return Reply(429, {"error": {"message": "slow down"}}, headers)


def server_error(status: int = 500) -> Reply:
    return Reply(status, {"error": {"message": "upstream is having a moment"}})


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        stub: MockLLM = self.server.stub  # type: ignore[attr-defined]
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        stub.record(self.path, {k.lower(): v for k, v in self.headers.items()}, body)

        reply = stub.next_reply()
        payload = reply.encoded()
        self.send_response(reply.status)
        for name, value in reply.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class MockLLM:
    """A running model endpoint. `base_url` is what PRAXIS_LLM_BASE_URL points at."""

    def __init__(self, *replies: Reply):
        self.replies = list(replies) or [Reply()]
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.stub = self  # type: ignore[attr-defined]
        # A short poll interval: `stop()` blocks for one of these, and a retry case
        # starts a fresh stub, so the default half-second would be most of this file's
        # runtime spent shutting servers down.
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def record(self, path: str, headers: dict[str, str], body: object) -> None:
        with self.lock:
            self.requests.append({"path": path, "headers": headers, "json": body})

    def next_reply(self) -> Reply:
        """The next scripted reply; the last one repeats once the queue runs dry."""
        with self.lock:
            return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    @property
    def calls(self) -> int:
        with self.lock:
            return len(self.requests)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
