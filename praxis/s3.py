#!/usr/bin/env python3
"""A minimal S3-compatible client — enough to mirror one directory, and nothing more.

Praxis's cloud backend needs four verbs (list · get · put · delete) against anything that
speaks S3: AWS itself, MinIO, Backblaze B2, Cloudflare R2, a local mock in the test
suite. This module is the **adapter** that keeps that four-verb surface stable while
`minio-py` does the protocol — the signing, the paging and the XML that used to live here
by hand were ~290 lines of `hmac` and `xml.etree` maintained for no gain over a pinned,
Apache-2.0 library with no boto3 in its dependency tree.

What the adapter is actually for is minio's *defaults*, which do not match what
`praxis/cloud.py` needs:

* **single-part uploads only.** minio switches to multipart above 5 MiB, and a multipart
  `ETag` is not the object's MD5 — which is exactly what `praxis/cloud.py` compares
  against a local file to decide whether it has changed. `put_object` therefore sizes the
  part so that any object the old client could PUT (up to S3's 5 GiB single-PUT ceiling)
  goes up in one request, and the `ETag` stays `md5_of(data)`.
* **path-style addressing**, which minio already picks for every non-AWS host. Virtual-host
  style is what breaks first against MinIO and local mocks.
* **bounded time.** `Backend.available()` calls in from the UI, so the client supplies its
  own urllib3 pool built from `timeout` with minio's five built-in retries cut down; the
  stock client would wait five minutes and retry a dead endpoint five times.
* **one error type.** `praxis/storage.py` catches `praxis.s3.S3Error`; minio raises four
  unrelated families plus urllib3's. Everything a caller can see is mapped back here, with
  the HTTP status on `.status` (0 when there never was one) and no credential in the text.

Credentials come from the backend's saved options and are never logged. Anonymous access
(no keys at all) stays a supported mode — a public bucket or the test mock needs none.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from itertools import islice
from urllib.parse import urlsplit

import certifi
import urllib3
from minio import Minio
from minio import error as _minio
from minio.helpers import MAX_PART_SIZE, MIN_PART_SIZE

#: Seconds any single request may take. A backend check must not hang the UI, and the
#: objects involved are small, so one timeout covers both connect and read.
DEFAULT_TIMEOUT = 10.0

#: How many times urllib3 may retry beneath minio. minio's own default is five with a
#: backoff, which turns an unreachable bucket into a multi-second stall inside a request
#: handler; one retry still absorbs a dropped keep-alive. Status codes are never retried —
#: they are answers, and `S3Error` is how a caller is told about them.
HTTP_RETRIES = 1


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


def _endpoint_parts(endpoint: str) -> tuple[str, bool]:
    """`http(s)://host[:port]` — the form the settings form saves — as minio wants it.

    minio takes `host[:port]` plus `secure=`, and refuses a path itself; anything after the
    host is handed straight through so that refusal happens (as a `ValueError` the caller
    turns into an `S3Error`) rather than being silently dropped here.
    """
    raw = endpoint.strip().rstrip("/")
    parsed = urlsplit(raw if "//" in raw else "//" + raw)
    return (parsed.netloc + parsed.path), (parsed.scheme or "https") != "http"


def _http_client(timeout: float) -> urllib3.PoolManager:
    """minio's pool, but on Praxis's clock and with its retries bounded."""
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=timeout, read=timeout),
        maxsize=10,
        cert_reqs="CERT_REQUIRED",
        ca_certs=os.environ.get("SSL_CERT_FILE") or certifi.where(),
        retries=urllib3.Retry(
            total=HTTP_RETRIES,
            connect=HTTP_RETRIES,
            read=HTTP_RETRIES,
            redirect=0,
            backoff_factor=0.1,
            status_forcelist=[],
        ),
    )


def _status_of(exc: _minio.S3Error) -> int:
    return int(getattr(getattr(exc, "response", None), "status", 0) or 0)


class S3Client:
    """One bucket on one endpoint, over `minio.Minio`.

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

        host, secure = _endpoint_parts(self.endpoint)
        signed = bool(self.access_key_id and self.secret_access_key)
        try:
            self._minio = Minio(
                host,
                access_key=self.access_key_id if signed else None,
                secret_key=self.secret_access_key if signed else None,
                session_token=self.session_token or None,
                secure=secure,
                region=self.region,
                http_client=_http_client(timeout),
            )
        except (ValueError, _minio.MinioException) as exc:
            raise S3Error(f"{self.endpoint}: {exc}") from exc

    # --- everything a caller can see is an S3Error --------------------------

    def _call(self, what: str, call, *args, **kwargs):
        """Run one minio call, and translate its whole error family into `S3Error`."""
        try:
            return call(*args, **kwargs)
        except _minio.S3Error as exc:
            status = _status_of(exc)
            raise S3Error(f"{what} -> {status} {exc.code}: {exc.message}".strip(),
                          status) from exc
        except _minio.ServerError as exc:
            raise S3Error(f"{what} -> {exc.status_code} {exc}", exc.status_code) from exc
        except _minio.InvalidResponseError as exc:
            # The only place minio keeps the status of a non-XML reply.
            status = int(getattr(exc, "_code", 0) or 0)
            raise S3Error(f"{what} -> {status} {exc}".strip(), status) from exc
        except (_minio.MinioException, urllib3.exceptions.HTTPError, OSError,
                ValueError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise S3Error(f"{self.endpoint}: {reason}") from exc

    def _where(self, key: str = "") -> str:
        return f"s3://{self.bucket}/{key}".rstrip("/")

    # --- the four verbs -----------------------------------------------------

    def head_bucket(self) -> None:
        """Raise `S3Error` unless the bucket is there and these credentials can read it."""
        self.list_objects(max_keys=1, exhaust=False)

    def list_objects(
        self, prefix: str = "", max_keys: int = 1000, exhaust: bool = True
    ) -> list[RemoteObject]:
        """Every object under `prefix`, following continuation tokens by default."""
        return self._call(f"LIST {self._where(prefix)}", self._list,
                          prefix, max_keys, exhaust)

    def _list(self, prefix: str, max_keys: int, exhaust: bool) -> list[RemoteObject]:
        # minio's public `list_objects` fixes `max-keys` at 1000, and `max_keys` is the
        # argument `head_bucket` uses to make its check one small request; paging is the
        # point, so this goes through the paging generator underneath it. The `<8` ceiling
        # on the dependency in pyproject.toml is what keeps that call honest.
        # No `encoding-type=url`: S3's XML escaping already carries every key Praxis
        # writes, and minio's `unquote_plus` of an un-encoded key would corrupt a `+`.
        page = self._minio._list_objects(  # noqa: SLF001 - see above
            self.bucket,
            prefix=prefix or None,
            delimiter=None,
            encoding_type=None,
            max_keys=max_keys,
        )
        rows = page if exhaust else islice(page, max_keys)
        return [
            RemoteObject(
                key=obj.object_name or "",
                size=int(obj.size or 0),
                etag=(obj.etag or "").strip('"'),
                modified=obj.last_modified.timestamp() if obj.last_modified else 0.0,
            )
            for obj in rows
        ]

    def get_object(self, key: str) -> bytes:
        return self._call(f"GET {self._where(key)}", self._get, key)

    def _get(self, key: str) -> bytes:
        response = self._minio.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put_object(self, key: str, data: bytes) -> str:
        """Store `data`; returns the ETag (the MD5 of the body for a single-part PUT)."""
        result = self._call(f"PUT {self._where(key)}", self._put, key, data)
        return (result.etag or "").strip('"')

    def _put(self, key: str, data: bytes):
        # A part at least as large as the body is one part, so minio never goes multipart
        # and the ETag stays the MD5 `praxis/cloud.py` compares against. minio clamps a
        # part to [5 MiB, 5 GiB], which is S3's own single-PUT ceiling.
        part_size = min(max(len(data), MIN_PART_SIZE), MAX_PART_SIZE)
        return self._minio.put_object(
            self.bucket, key, io.BytesIO(data), len(data),
            content_type="application/octet-stream", part_size=part_size,
        )

    def delete_object(self, key: str) -> None:
        self._call(f"DELETE {self._where(key)}",
                   self._minio.remove_object, self.bucket, key)


def md5_of(data: bytes) -> str:
    """The hex digest a single-part PUT of `data` would come back with as its ETag."""
    return hashlib.md5(data).hexdigest()  # noqa: S324 - S3's ETag, not a security digest
