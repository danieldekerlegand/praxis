"""A tiny S3-compatible object store, so the cloud backend can be tested for real.

`praxis/s3.py` speaks SigV4 over HTTP to whatever is at an endpoint. Mocking that at the
Python level — patching `S3Client` — would test the mock; this serves the actual protocol
on a loopback port so the request that gets signed is the request that gets parsed, and a
sync in a *separate process* can reach the same bucket (which is what
`tests/test_storage_backends.py` needs to prove a cloud round trip survives a restart).

Deliberately incomplete: PUT/GET/DELETE one key and ListObjectsV2, path-style addressing,
in-memory, single-part. That is exactly the surface `praxis/cloud.py` uses, and the parts
that are missing are the parts a directory mirror never calls.

Signatures are parsed but not verified — the fixture is here to exercise the wire format
and the sync logic, not to reimplement AWS's authentication. `require_auth=True` still
rejects an unsigned request, which is enough to catch "the client forgot to sign".
"""

from __future__ import annotations

import email.utils
import hashlib
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


class Bucket:
    """One bucket's objects: key -> (bytes, last-modified epoch seconds)."""

    def __init__(self, name: str):
        self.name = name
        self.objects: dict[str, tuple[bytes, float]] = {}
        self.lock = threading.Lock()

    def put(self, key: str, data: bytes, modified: float) -> str:
        with self.lock:
            self.objects[key] = (data, modified)
        return hashlib.md5(data).hexdigest()  # noqa: S324 - S3's ETag

    def keys(self) -> list[str]:
        with self.lock:
            return sorted(self.objects)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- plumbing -----------------------------------------------------------

    def log_message(self, *args):  # keep pytest output clean
        pass

    @property
    def store(self) -> "MockS3":
        return self.server.store  # type: ignore[attr-defined]

    def _split(self) -> tuple[str, str, dict]:
        """`(bucket, key, query)` from a path-style URL."""
        parsed = urllib.parse.urlsplit(self.path)
        parts = urllib.parse.unquote(parsed.path).lstrip("/").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return bucket, key, query

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        body = (f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code>'
                f"<Message>{escape(message)}</Message></Error>").encode()
        self._send(status, body, {"Content-Type": "application/xml"})

    def _bucket(self, name: str):
        if self.store.require_auth and "Authorization" not in self.headers:
            self._error(403, "AccessDenied", "unsigned request")
            return None
        bucket = self.store.buckets.get(name)
        if bucket is None:
            self._error(404, "NoSuchBucket", f"no bucket {name!r}")
        return bucket

    # --- the four verbs -----------------------------------------------------

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        name, key, query = self._split()
        bucket = self._bucket(name)
        if bucket is None:
            return
        if not key:
            return self._list(bucket, query)
        with bucket.lock:
            found = bucket.objects.get(key)
        if found is None:
            return self._error(404, "NoSuchKey", key)
        data, modified = found
        self._send(200, data, {
            "ETag": f'"{hashlib.md5(data).hexdigest()}"',  # noqa: S324
            "Last-Modified": email.utils.formatdate(modified, usegmt=True),
            "Content-Type": "application/octet-stream",
        })

    def do_PUT(self):  # noqa: N802
        name, key, _ = self._split()
        bucket = self._bucket(name)
        if bucket is None:
            return
        if not key:
            return self._error(400, "InvalidRequest", "no key")
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else b""
        etag = bucket.put(key, data, self.store.clock())
        self.store.puts.append(key)
        self._send(200, b"", {"ETag": f'"{etag}"'})

    def do_DELETE(self):  # noqa: N802
        name, key, _ = self._split()
        bucket = self._bucket(name)
        if bucket is None:
            return
        with bucket.lock:
            bucket.objects.pop(key, None)
        self._send(204)

    def _list(self, bucket: Bucket, query: dict) -> None:
        prefix = query.get("prefix", "")
        max_keys = int(query.get("max-keys") or 1000)
        after = query.get("continuation-token", "")
        with bucket.lock:
            keys = sorted(k for k in bucket.objects if k.startswith(prefix) and k > after)
            page, truncated = keys[:max_keys], len(keys) > max_keys
            rows = []
            for key in page:
                data, modified = bucket.objects[key]
                stamp = email.utils.formatdate(modified, usegmt=True)
                iso = email.utils.parsedate_to_datetime(stamp).isoformat().replace(
                    "+00:00", "Z")
                rows.append(
                    f"<Contents><Key>{escape(key)}</Key><Size>{len(data)}</Size>"
                    f'<ETag>&quot;{hashlib.md5(data).hexdigest()}&quot;</ETag>'  # noqa: S324
                    f"<LastModified>{iso}</LastModified></Contents>"
                )
        token = (f"<NextContinuationToken>{escape(page[-1])}</NextContinuationToken>"
                 if truncated and page else "")
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<ListBucketResult xmlns="{_NS}">'
            f"<Name>{escape(bucket.name)}</Name><Prefix>{escape(prefix)}</Prefix>"
            f"<KeyCount>{len(page)}</KeyCount>"
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
            f"{token}{''.join(rows)}</ListBucketResult>"
        ).encode()
        self._send(200, body, {"Content-Type": "application/xml"})


class MockS3:
    """A running object store. `endpoint` is what a cloud backend's options point at."""

    def __init__(self, buckets=("praxis",), require_auth: bool = True):
        self.buckets = {name: Bucket(name) for name in buckets}
        self.require_auth = require_auth
        self.puts: list[str] = []
        self._now: float | None = None
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.store = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def clock(self) -> float:
        """When a PUT is stamped. Overridable so a test can make the bucket's copy older."""
        import time
        return self._now if self._now is not None else time.time()

    def freeze(self, when: float | None) -> None:
        self._now = when

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def options(self, bucket: str = "praxis", prefix: str = "") -> dict:
        """A cloud backend's options pointing here."""
        return {
            "endpoint": self.endpoint,
            "bucket": bucket,
            "prefix": prefix,
            "region": "us-east-1",
            "access_key_id": "praxis-test",
            "secret_access_key": "praxis-test-secret",
        }

    def keys(self, bucket: str = "praxis") -> list[str]:
        return self.buckets[bucket].keys()

    def body(self, key: str, bucket: str = "praxis") -> bytes:
        return self.buckets[bucket].objects[key][0]

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
