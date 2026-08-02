#!/usr/bin/env python3
"""A minimal S3-compatible client — enough to mirror one directory, and nothing more.

Praxis's cloud backend needs four verbs (list · get · put · delete) against anything that
speaks S3: AWS itself, MinIO, Backblaze B2, Cloudflare R2, a local mock in the test
suite. That is a small enough surface that `urllib` plus `hmac` beats taking a dependency
on boto3 — the core of this project is deliberately dependency-light (see `pyproject.toml`:
only `nbformat` is required), and a storage backend is not a good reason to change that.

Two deliberate limits, because a directory mirror needs neither:

* **path-style addressing only** (`<endpoint>/<bucket>/<key>`). Virtual-host style is what
  breaks first against MinIO and local mocks, and every S3 implementation supports path
  style.
* **single-part uploads only**. That keeps `ETag` equal to the object's MD5, which is what
  `praxis/cloud.py` compares against a local file to decide whether it has changed. A
  notebook is kilobytes; nothing here is near the 5 GB single-PUT ceiling.

Credentials come from the backend's saved options and are never logged — `S3Error` carries
the status and the body of a failure, and the signing inputs stay out of it.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterator

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

#: Seconds any single request may take. A backend check must not hang the UI, and the
#: objects involved are small, so one timeout covers both.
DEFAULT_TIMEOUT = 10.0


class S3Error(RuntimeError):
    """A request failed. `status` is the HTTP code (0 when we never got one)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RemoteObject:
    """One object as `ListObjectsV2` reports it."""

    key: str
    size: int
    etag: str
    modified: float  # POSIX timestamp, UTC


def _quote(value: str, safe: str = "/~") -> str:
    return urllib.parse.quote(value, safe=safe)


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def _parse_iso(value: str) -> float:
    """S3's `LastModified` (`2026-08-01T12:00:00.000Z`) as a POSIX timestamp."""
    text = (value or "").strip().replace("Z", "+00:00")
    try:
        stamp = _datetime.datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_datetime.timezone.utc)
    return stamp.timestamp()


def _localname(tag: str) -> str:
    """`{http://s3.amazonaws.com/doc/2006-03-01/}Key` -> `Key`.

    Implementations disagree about whether the list response is namespaced (AWS uses one,
    several mocks don't), so every read of the XML goes through this.
    """
    return tag.rsplit("}", 1)[-1]


def _find(node: ET.Element, name: str) -> str:
    for child in node:
        if _localname(child.tag) == name:
            return (child.text or "").strip()
    return ""


class S3Client:
    """One bucket on one endpoint, signed with SigV4.

    `endpoint` is the scheme and host (`https://s3.us-east-1.amazonaws.com`,
    `http://127.0.0.1:9000`); the bucket is always the first path segment.
    """

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key_id: str = "",
        secret_access_key: str = "",
        region: str = "us-east-1",
        session_token: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.endpoint = (endpoint or "").rstrip("/")
        self.bucket = (bucket or "").strip("/")
        self.access_key_id = access_key_id or ""
        self.secret_access_key = secret_access_key or ""
        self.region = region or "us-east-1"
        self.session_token = session_token or ""
        self.timeout = timeout
        if not self.endpoint:
            raise S3Error("no endpoint — an S3-compatible URL is required")
        if not self.bucket:
            raise S3Error("no bucket")

    # --- signing ------------------------------------------------------------

    def _signing_key(self, stamp: str) -> bytes:
        key = _sign(f"AWS4{self.secret_access_key}".encode(), stamp)
        key = _sign(key, self.region)
        key = _sign(key, SERVICE)
        return _sign(key, "aws4_request")

    def _headers(
        self, method: str, path: str, query: dict, payload: bytes, extra: dict | None = None
    ) -> dict:
        """SigV4 headers for one request. Anonymous when no access key is configured.

        A mock or a public bucket needs no credentials, and refusing to talk to one would
        make the test suite less honest, not more — so an unsigned request is a supported
        mode rather than an error.
        """
        host = urllib.parse.urlsplit(self.endpoint).netloc
        payload_hash = hashlib.sha256(payload).hexdigest() if payload else EMPTY_SHA256
        now = _datetime.datetime.now(_datetime.timezone.utc)
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        stamp = now.strftime("%Y%m%d")

        headers = {
            "Host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amzdate,
            **(extra or {}),
        }
        if self.session_token:
            headers["x-amz-security-token"] = self.session_token
        if not (self.access_key_id and self.secret_access_key):
            return headers

        canonical_query = "&".join(
            f"{_quote(k, '~')}={_quote(str(v), '~')}" for k, v in sorted(query.items())
        )
        signed = sorted(headers, key=str.lower)
        canonical_headers = "".join(
            f"{name.lower()}:{str(headers[name]).strip()}\n" for name in signed
        )
        signed_headers = ";".join(name.lower() for name in signed)
        canonical_request = "\n".join([
            method,
            path,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ])
        scope = f"{stamp}/{self.region}/{SERVICE}/aws4_request"
        to_sign = "\n".join([
            ALGORITHM,
            amzdate,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])
        signature = hmac.new(
            self._signing_key(stamp), to_sign.encode(), hashlib.sha256
        ).hexdigest()
        headers["Authorization"] = (
            f"{ALGORITHM} Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers

    # --- the wire -----------------------------------------------------------

    def _request(
        self,
        method: str,
        key: str = "",
        query: dict | None = None,
        payload: bytes = b"",
        extra_headers: dict | None = None,
    ) -> tuple[int, dict, bytes]:
        query = dict(query or {})
        path = "/" + _quote(f"{self.bucket}/{key}".rstrip("/") if key else self.bucket)
        headers = self._headers(method, path, query, payload, extra_headers)
        url = self.endpoint + path
        if query:
            url += "?" + "&".join(
                f"{_quote(k, '~')}={_quote(str(v), '~')}" for k, v in sorted(query.items())
            )
        request = urllib.request.Request(url, data=payload or None, method=method)
        for name, value in headers.items():
            if name != "Host":  # urllib sets Host itself, from the URL
                request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()[:400].decode("utf-8", "replace")
            raise S3Error(f"{method} {path} -> {exc.code} {body}".strip(), exc.code) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            raise S3Error(f"{self.endpoint}: {reason}") from exc

    # --- the four verbs -----------------------------------------------------

    def head_bucket(self) -> None:
        """Raise `S3Error` unless the bucket is there and these credentials can read it."""
        self.list_objects(max_keys=1, exhaust=False)

    def list_objects(
        self, prefix: str = "", max_keys: int = 1000, exhaust: bool = True
    ) -> list[RemoteObject]:
        """Every object under `prefix`, following continuation tokens by default."""
        found: list[RemoteObject] = []
        token = ""
        while True:
            query = {"list-type": "2", "max-keys": str(max_keys)}
            if prefix:
                query["prefix"] = prefix
            if token:
                query["continuation-token"] = token
            _, _, body = self._request("GET", query=query)
            objects, token = _parse_listing(body)
            found.extend(objects)
            if not exhaust or not token:
                return found

    def get_object(self, key: str) -> bytes:
        return self._request("GET", key)[2]

    def put_object(self, key: str, data: bytes) -> str:
        """Store `data`; returns the ETag (the MD5 of the body for a single-part PUT)."""
        _, headers, _ = self._request(
            "PUT", key, payload=data,
            extra_headers={"Content-Length": str(len(data)),
                           "Content-Type": "application/octet-stream"},
        )
        return (headers.get("ETag") or headers.get("etag") or "").strip('"')

    def delete_object(self, key: str) -> None:
        self._request("DELETE", key)


def _parse_listing(body: bytes) -> tuple[list[RemoteObject], str]:
    """`(objects, continuation token)` from a ListObjectsV2 response."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise S3Error(f"unreadable listing from the bucket: {exc}") from exc

    objects: list[RemoteObject] = []
    token = ""
    for node in root:
        name = _localname(node.tag)
        if name == "Contents":
            objects.append(RemoteObject(
                key=_find(node, "Key"),
                size=int(_find(node, "Size") or 0),
                etag=_find(node, "ETag").strip('"'),
                modified=_parse_iso(_find(node, "LastModified")),
            ))
        elif name == "NextContinuationToken":
            token = (node.text or "").strip()
        elif name == "IsTruncated" and (node.text or "").strip().lower() != "true":
            token = token or ""
    return objects, token


def md5_of(data: bytes) -> str:
    """The hex digest a single-part PUT of `data` would come back with as its ETag."""
    return hashlib.md5(data).hexdigest()  # noqa: S324 - S3's ETag, not a security digest


def walk_files(root) -> Iterator:  # pragma: no cover - trivial, exercised via cloud.sync
    """Every regular file under `root`, in a stable order."""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        yield path
