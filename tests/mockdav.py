"""A tiny WebDAV server, so the share backend can be tested for real.

`praxis/webdav.py` speaks HTTP with five extra verbs to whatever is at a URL. Mocking that
at the Python level — patching `WebDAVClient` — would test the mock; this serves the actual
protocol on a loopback port, so the `PROPFIND` that gets built is the `PROPFIND` that gets
parsed, and a sync in a *separate process* can reach the same share (which is what
`tests/test_storage_backends.py` needs to prove a round trip survives a restart).

Deliberately incomplete, and deliberately awkward in the three places real servers are:

* **`Depth: infinity` is refused** with 403, the way Nextcloud and `mod_dav` refuse it.
  A client that took the one-request shortcut would fail here, which is the point.
* **`ETag` is opaque** — a version counter, not the body's MD5. Anything that compared it
  with a local digest (as the S3 mirror legitimately does) would loop forever, so this
  keeps `praxis/share.py` honest about which side changed.
* **A `PUT` into a missing collection is 409**, so `MKCOL` has to have happened first.

Credentials are checked for presence, not verified — the fixture exercises the wire and
the sync logic, not authentication. `require_auth=True` still rejects an unsigned request,
which is enough to catch "the client forgot to send its password".
"""

from __future__ import annotations

import email.utils
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

#: Everything hangs under this path, so the client has to map an `href` back to a
#: relative key rather than assuming the server root is its root.
BASE = "/dav"


class Share:
    """One collection tree: files as key -> (bytes, modified, etag), plus its directories."""

    def __init__(self):
        self.files: dict[str, tuple[bytes, float, str]] = {}
        self.dirs: set[str] = {""}
        self.lock = threading.Lock()
        self._version = 0

    def put(self, key: str, data: bytes, modified: float) -> str:
        with self.lock:
            self._version += 1
            etag = f"v{self._version}"
            self.files[key] = (data, modified, etag)
            return etag

    def mkcol(self, key: str) -> None:
        with self.lock:
            self.dirs.add(key)

    def keys(self) -> list[str]:
        with self.lock:
            return sorted(self.files)

    def body(self, key: str) -> bytes:
        with self.lock:
            return self.files[key][0]

    def clear(self) -> None:
        with self.lock:
            self.files.clear()


def _parent(key: str) -> str:
    return key.rsplit("/", 1)[0] if "/" in key else ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output clean
        pass

    @property
    def store(self) -> "MockDAV":
        return self.server.store  # type: ignore[attr-defined]

    # --- plumbing -----------------------------------------------------------

    def _key(self) -> str | None:
        """The path under `BASE`, or `None` when the request is outside the share."""
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path != BASE and not path.startswith(BASE + "/"):
            return None
        return path[len(BASE):].strip("/")

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, message.encode(), {"Content-Type": "text/plain"})

    def _open(self) -> str | None:
        """The key for this request, once auth and addressing have been checked."""
        if self.store.require_auth and "Authorization" not in self.headers:
            self._error(401, "unauthenticated")
            return None
        key = self._key()
        if key is None:
            self._error(404, "not this server's share")
            return None
        return key

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # --- the verbs ----------------------------------------------------------

    def do_PROPFIND(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        key = self._open()
        if key is None:
            return
        depth = (self.headers.get("Depth") or "infinity").strip().lower()
        self._body()  # drain the request body; the properties asked for are ignored
        if depth not in ("0", "1"):
            return self._error(403, "propfind-finite-depth: Depth: infinity is disabled")
        share = self.store.share
        with share.lock:
            is_dir = key in share.dirs
            is_file = key in share.files
            if not is_dir and not is_file:
                return self._error(404, f"no such collection or file: {key!r}")
            rows = [self._entry(key, is_dir)]
            if is_dir and depth == "1":
                children = [d for d in share.dirs if d and _parent(d) == key]
                children += [f for f in share.files if _parent(f) == key]
                rows += [self._entry(child, child in share.dirs) for child in sorted(children)]
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<D:multistatus xmlns:D="DAV:">{"".join(rows)}</D:multistatus>'
        ).encode()
        self._send(207, body, {"Content-Type": 'application/xml; charset="utf-8"'})

    def _entry(self, key: str, is_dir: bool) -> str:
        """One `<D:response>`. Called with the share's lock already held."""
        href = escape(urllib.parse.quote(f"{BASE}/{key}" if key else BASE))
        if is_dir:
            props = "<D:resourcetype><D:collection/></D:resourcetype>"
        else:
            data, modified, etag = self.store.share.files[key]
            props = (
                "<D:resourcetype/>"
                f"<D:getcontentlength>{len(data)}</D:getcontentlength>"
                f"<D:getlastmodified>{email.utils.formatdate(modified, usegmt=True)}"
                "</D:getlastmodified>"
                f"<D:getetag>&quot;{escape(etag)}&quot;</D:getetag>"
            )
        return (
            f"<D:response><D:href>{href}{'/' if is_dir else ''}</D:href><D:propstat>"
            f"<D:prop>{props}</D:prop><D:status>HTTP/1.1 200 OK</D:status>"
            "</D:propstat></D:response>"
        )

    def do_GET(self):  # noqa: N802
        key = self._open()
        if key is None:
            return
        share = self.store.share
        with share.lock:
            found = share.files.get(key)
        if found is None:
            return self._error(404, f"no such file: {key!r}")
        data, modified, etag = found
        self._send(200, data, {
            "ETag": f'"{etag}"',
            "Last-Modified": email.utils.formatdate(modified, usegmt=True),
            "Content-Type": "application/octet-stream",
        })

    def do_PUT(self):  # noqa: N802
        key = self._open()
        if key is None:
            return
        data = self._body()
        if not key:
            return self._error(400, "no key")
        share = self.store.share
        with share.lock:
            missing = _parent(key) not in share.dirs
        if missing:
            return self._error(409, f"no collection {_parent(key)!r} to put {key!r} into")
        etag = share.put(key, data, self.store.clock())
        self.store.puts.append(key)
        self._send(201, b"", {"ETag": f'"{etag}"'})

    def do_MKCOL(self):  # noqa: N802
        key = self._open()
        if key is None:
            return
        share = self.store.share
        with share.lock:
            if key in share.dirs or key in share.files:
                return self._error(405, f"{key!r} is already there")
            if _parent(key) not in share.dirs:
                return self._error(409, f"no collection {_parent(key)!r}")
        share.mkcol(key)
        self.store.mkcols.append(key)
        self._send(201)

    def do_DELETE(self):  # noqa: N802
        key = self._open()
        if key is None:
            return
        share = self.store.share
        with share.lock:
            share.files.pop(key, None)
            share.dirs.discard(key)
        self.store.deletes.append(key)
        self._send(204)


class MockDAV:
    """A running WebDAV share. `url` is what a webdav backend's options point at."""

    def __init__(self, require_auth: bool = True):
        self.share = Share()
        self.require_auth = require_auth
        self.puts: list[str] = []
        self.mkcols: list[str] = []
        # Recorded so a test can assert what a sync *didn't* do: "never deletes" is a
        # claim about the wire, and an empty list here is the whole of the evidence.
        self.deletes: list[str] = []
        self._now: float | None = None
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.store = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def clock(self) -> float:
        """When a PUT is stamped. Overridable so a test can make the share's copy older."""
        import time
        return self._now if self._now is not None else time.time()

    def freeze(self, when: float | None) -> None:
        self._now = when

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{BASE}"

    def options(self, folder: str = "") -> dict:
        """A webdav backend's options pointing here."""
        return {
            "url": self.url,
            "folder": folder,
            "username": "ada",
            "password": "praxis-test-password",
        }

    def make(self, folder: str) -> None:
        """Create a collection (and its parents) the way the account owner would have."""
        parts = [p for p in folder.split("/") if p]
        for i in range(len(parts)):
            self.share.mkcol("/".join(parts[: i + 1]))

    def keys(self) -> list[str]:
        return self.share.keys()

    def body(self, key: str) -> bytes:
        return self.share.body(key)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
