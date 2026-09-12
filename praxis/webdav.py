#!/usr/bin/env python3
"""A minimal WebDAV client — enough to mirror one directory, and nothing more.

The other remote Praxis speaks is an object store (`praxis/s3.py`). This is the one most
people already have without buying anything: Nextcloud, ownCloud, a Synology, Box, a
Fastmail file store, `rclone serve webdav`, Apache's `mod_dav`. All of them are HTTP with
five extra verbs, which is a small enough surface that `urllib` beats a dependency: there
is no maintained WebDAV client to adopt the way `praxis/s3.py` adopted minio-py, and a
handful of verbs is not worth vendoring one. [CORRECTED 2026-09-12 — this said the core
requires only `nbformat`, which was already false once `nbgrader` was pinned.]

Five verbs, and two deliberate limits:

* **`PROPFIND` at `Depth: 1`, walked recursively.** `Depth: infinity` is one request
  instead of many, and it is the first thing a real server turns off — Nextcloud and
  Apache both refuse it by default (403 `propfind-finite-depth`). Walking is slower and
  works everywhere, which is the right trade for a few hundred notebooks.
* **Basic auth over whatever scheme the URL names.** Digest and OAuth are what a client
  with a browser does; an app-password over `https://` is what these servers actually
  hand out for file access. The credentials come from the backend's saved options and are
  never logged — `WebDAVError` carries the status and the body of a failure, nothing else.

`ETag` here is **opaque**: unlike S3's, it is not the body's MD5 and must never be
compared with one. It is a token whose *change* means "this file moved on the server",
which is all `praxis/share.py` asks of it.
"""

from __future__ import annotations

import base64
import email.utils
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

#: Seconds any single request may take. A backend check must not hang the UI, and the
#: files involved are notebooks, so one timeout covers both.
DEFAULT_TIMEOUT = 10.0

#: The body sent with every `PROPFIND`. Asking for named properties rather than `allprop`
#: keeps the response small on servers that store hundreds of them per file.
PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:"><D:prop>'
    "<D:resourcetype/><D:getcontentlength/><D:getlastmodified/><D:getetag/>"
    "</D:prop></D:propfind>"
).encode()


class WebDAVError(RuntimeError):
    """A request failed. `status` is the HTTP code (0 when we never got one)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RemoteFile:
    """One file as `PROPFIND` reports it, addressed relative to the client's root."""

    rel: str
    size: int
    etag: str
    modified: float  # POSIX timestamp, UTC


def _localname(tag: str) -> str:
    """`{DAV:}getetag` -> `getetag`.

    Servers disagree about the prefix they bind `DAV:` to (`D:`, `d:`, `lp1:`), and a few
    mocks send no namespace at all, so every read of the XML goes through this.
    """
    return tag.rsplit("}", 1)[-1].lower()


def _child(node: ET.Element, name: str) -> ET.Element | None:
    for child in node:
        if _localname(child.tag) == name:
            return child
    return None


def _text(node: ET.Element | None, name: str) -> str:
    child = _child(node, name) if node is not None else None
    return (child.text or "").strip() if child is not None else ""


def _parse_http_date(value: str) -> float:
    """`getlastmodified` (RFC 1123: `Wed, 19 Aug 2026 12:00:00 GMT`) as a timestamp."""
    if not value:
        return 0.0
    try:
        return email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def normalize_folder(folder: str) -> str:
    """The folder under the collection URL, as `''` or `'a/b'`."""
    return "/".join(part for part in str(folder or "").strip().split("/") if part)


class WebDAVClient:
    """One collection on one server: `<url>/<folder>/…`.

    `url` is the collection the server hands out (`https://cloud.example/remote.php/dav/
    files/ada`), and `folder` is the directory under it Praxis owns. Keeping them apart is
    what lets the settings form ask for the account URL once and the folder separately,
    the same way `bucket` and `prefix` are separate for S3.
    """

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        folder: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.url = (url or "").strip().rstrip("/")
        if not self.url:
            raise WebDAVError("no server URL — a WebDAV collection URL is required")
        scheme = urllib.parse.urlsplit(self.url).scheme
        if scheme not in ("http", "https"):
            raise WebDAVError(f"{self.url!r} is not an http(s) URL")
        self.folder = normalize_folder(folder)
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        # MKCOL is idempotent but not free; a mirror push touches the same few directories
        # over and over, so remember the ones this client has already made sure of.
        self._collections: set[str] = set()

    @property
    def root(self) -> str:
        """The collection URL Praxis writes into, folder included."""
        return f"{self.url}/{_quote(self.folder)}" if self.folder else self.url

    @property
    def root_path(self) -> str:
        """The root as a decoded path, which is what `href`s have to be measured against."""
        return urllib.parse.unquote(urllib.parse.urlsplit(self.root).path).rstrip("/")

    # --- the wire -----------------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        headers = dict(extra or {})
        if self.username or self.password:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _request(
        self,
        method: str,
        rel: str = "",
        payload: bytes = b"",
        extra_headers: dict | None = None,
    ) -> tuple[int, dict, bytes]:
        url = f"{self.root}/{_quote(rel)}" if rel else self.root
        request = urllib.request.Request(url, data=payload or None, method=method)
        for name, value in self._headers(extra_headers).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()[:400].decode("utf-8", "replace")
            path = urllib.parse.urlsplit(url).path
            raise WebDAVError(f"{method} {path} -> {exc.code} {body}".strip(), exc.code) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            raise WebDAVError(f"{self.url}: {reason}") from exc

    # --- the five verbs -----------------------------------------------------

    def propfind(self, rel: str = "", depth: str = "1") -> list[tuple[str, bool, RemoteFile]]:
        """`(rel, is a collection, its properties)` for one collection and its children."""
        _, _, body = self._request(
            "PROPFIND", rel, PROPFIND_BODY,
            {"Depth": depth, "Content-Type": 'application/xml; charset="utf-8"'},
        )
        return self._parse(body)

    def _parse(self, body: bytes) -> list[tuple[str, bool, RemoteFile]]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise WebDAVError(f"unreadable listing from the server: {exc}") from exc

        base = self.root_path
        entries: list[tuple[str, bool, RemoteFile]] = []
        for node in root:
            if _localname(node.tag) != "response":
                continue
            href = _text(node, "href")
            path = urllib.parse.unquote(urllib.parse.urlsplit(href).path).rstrip("/")
            if path != base and not path.startswith(base + "/"):
                continue  # a server that answered about something outside our root
            rel = path[len(base):].strip("/")
            # A server may answer about one file with several `propstat` blocks — the
            # properties it has, and a 404 block listing the ones it doesn't. Only the
            # 200 block is ours to read.
            prop = None
            for propstat in node:
                if _localname(propstat.tag) != "propstat":
                    continue
                status = _text(propstat, "status")
                if status and " 200 " not in f" {status} ":
                    continue
                found = _child(propstat, "prop")
                if found is not None:
                    prop = found
            if prop is None:
                prop = _child(node, "prop")
            if prop is None:
                continue
            resourcetype = _child(prop, "resourcetype")
            is_dir = resourcetype is not None and _child(resourcetype, "collection") is not None
            entries.append((rel, is_dir, RemoteFile(
                rel=rel,
                size=int(_text(prop, "getcontentlength") or 0),
                etag=_text(prop, "getetag").strip('"'),
                modified=_parse_http_date(_text(prop, "getlastmodified")),
            )))
        return entries

    def check(self) -> None:
        """Raise `WebDAVError` unless the root collection is there and readable."""
        entries = self.propfind(depth="0")
        if not entries:
            raise WebDAVError(f"{self.root} did not answer as a WebDAV collection")
        if not entries[0][1]:
            raise WebDAVError(f"{self.root} is a file, not a collection")

    def list_files(self) -> list[RemoteFile]:
        """Every file under the root, walked one `Depth: 1` request per collection."""
        found: list[RemoteFile] = []
        seen: set[str] = set()
        pending = [""]
        while pending:
            here = pending.pop()
            for rel, is_dir, info in self.propfind(here):
                if rel == here or rel in seen:
                    continue
                seen.add(rel)
                if is_dir:
                    pending.append(rel)
                else:
                    found.append(info)
        return sorted(found, key=lambda f: f.rel)

    def get_file(self, rel: str) -> bytes:
        return self._request("GET", rel)[2]

    def put_file(self, rel: str, data: bytes) -> str:
        """Store `data`, making the collections above it first. Returns its new ETag.

        Not every server sends an `ETag` back from a `PUT` (the spec only recommends it),
        so a missing one is asked for rather than guessed — the sync stores that token as
        "what the server had when we agreed", and a wrong one would re-copy the file
        forever.
        """
        self.ensure_collection(rel.rsplit("/", 1)[0] if "/" in rel else "")
        _, headers, _ = self._request(
            "PUT", rel, data,
            {"Content-Length": str(len(data)), "Content-Type": "application/octet-stream"},
        )
        etag = (headers.get("ETag") or headers.get("etag") or "").strip('"')
        if etag:
            return etag
        stat = self.stat(rel)
        return stat.etag if stat is not None else ""

    def stat(self, rel: str) -> RemoteFile | None:
        """One file's properties, or `None` if the server does not have it."""
        try:
            entries = self.propfind(rel, depth="0")
        except WebDAVError as exc:
            if exc.status == 404:
                return None
            raise
        return entries[0][2] if entries else None

    def ensure_collection(self, rel: str) -> None:
        """`MKCOL` every missing directory down to `rel`. Existing ones are not an error."""
        parts = [p for p in str(rel or "").split("/") if p]
        for i in range(len(parts)):
            path = "/".join(parts[: i + 1])
            if path in self._collections:
                continue
            try:
                self._request("MKCOL", path)
            except WebDAVError as exc:
                # 405 is "there already", which is the usual answer and the point of the
                # call. 301 is a server redirecting a collection to its trailing-slash
                # form — also there. Anything else is a real failure.
                if exc.status not in (301, 405):
                    raise
            self._collections.add(path)

    def delete_file(self, rel: str) -> None:
        self._request("DELETE", rel)


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="/~")
