#!/usr/bin/env python3
"""The WebDAV backend's working copy, and how it gets to and from the share.

Same shape as `praxis/cloud.py`, for the same reason: every other part of Praxis writes
with `Path` — `nbformat.write`, `json.dump`, a `glob` over a module — so a remote is a
**local mirror plus a sync**, never a filesystem the writers have to learn about.

    <app dir>/webdav/<host>[-<folder>]/      the mirror — an ordinary storage root
    <url>/<folder>/subjects/…                the same tree, on the server

The mirror is what `subjects_dir()` and `progress_dir()` resolve to, so the app is fully
usable with the network down; what fails when the server is unreachable is the *sync*, and
it fails out loud (`WebDAVError`) rather than pretending. `pull()` runs when the backend is
selected, so a second machine picking the same share gets the work already there.

The merge rule is the one `docs/reference/storage.md` promises for every mirrored backend:
per file, **the side that changed wins**, decided by content and not by clocks.
`.praxis-sync.json` in the mirror records what both sides had at the end of the last sync,
and a timestamp is consulted only for the genuine conflict — both sides edited since then.

One thing differs from the S3 mirror, and it is the whole reason this file exists rather
than a second caller of `praxis/cloud.py`. S3's `ETag` *is* the body's MD5, so one digest
describes both sides. A WebDAV `ETag` is **opaque** — Nextcloud's is a random token, Apache's
is inode+size+mtime — so "did the server's copy change?" and "did ours?" are two different
questions with two different answers, and the index records both:

    {"subjects/x/curriculum.json": {"local": "<sha256 of our bytes>", "remote": "<etag>"}}

Where there is no entry yet (a first sync, or an index that was lost) the file is fetched
and compared byte for byte, which is the only honest way to ask "are these the same?" when
the tokens are not comparable.

A sync **never deletes**. A share that has lost a file cannot take a notebook off your
disk, and a mirror you cleared cannot empty the share. Removing something is a thing the
user does in one place, on purpose, not something a background copy infers.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from praxis.webdav import WebDAVClient, WebDAVError, normalize_folder

#: What both sides agreed on last time, per file. Lives in the mirror (copy the folder and
#: the sync state comes with it) and is the one path never synced.
INDEX_FILE = ".praxis-sync.json"

#: Only consulted for a true conflict — both sides changed since the last sync — and then
#: only as a margin: a difference smaller than this is not evidence of anything, so the
#: local copy stands. `getlastmodified` is whole seconds; local mtimes are finer.
SKEW = 2.0

#: Option keys a WebDAV backend understands. `describe()` offers these to the UI.
OPTION_KEYS = ("url", "folder", "username", "password")


@dataclass
class SyncResult:
    """What one `sync()` moved — reported back to the UI, and to the progress log."""

    pulled: list[str] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    remote: int = 0
    local: int = 0

    def to_dict(self) -> dict:
        return {
            "pulled": sorted(self.pulled),
            "pushed": sorted(self.pushed),
            "remote": self.remote,
            "local": self.local,
            "moved": len(self.pulled) + len(self.pushed),
        }


def client_for(options: dict, timeout: float | None = None) -> WebDAVClient:
    """A `WebDAVClient` for a backend's saved options. Raises `WebDAVError` if unusable."""
    kwargs = {
        "url": str(options.get("url") or ""),
        "username": str(options.get("username") or ""),
        "password": str(options.get("password") or ""),
        "folder": folder_for(options),
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return WebDAVClient(**kwargs)


def folder_for(options: dict) -> str:
    """The directory under the collection URL, normalised to `''` or `'a/b'`."""
    return normalize_folder(options.get("folder"))


def mirror_name(options: dict) -> str:
    """A stable, filesystem-safe directory name for one server+folder pair."""
    import urllib.parse

    host = urllib.parse.urlsplit(str(options.get("url") or "")).netloc or "webdav"
    raw = "-".join(p for p in (host, folder_for(options)) if p)
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in raw).strip("-") or "webdav"


def reachable(options: dict, timeout: float = 5.0) -> tuple[bool, str]:
    """`(can we talk to the share right now, why not)`. Never raises.

    Called from `Backend.available()`, so it must answer quickly and it must answer
    *now* — a network share is exactly the kind of root that is there on one request and
    gone on the next.
    """
    try:
        client = client_for(options, timeout=timeout)
    except WebDAVError as exc:
        return False, str(exc)
    try:
        client.check()
    except WebDAVError as exc:
        # `exc` already names the server, so this says which *collection* was wanted.
        return False, f"cannot reach {client.root} — {exc}"
    return True, ""


# --- the mirror -------------------------------------------------------------


def digest(data: bytes) -> str:
    """How this module answers "are these the same bytes?" for the local side."""
    return hashlib.sha256(data).hexdigest()


def _local_files(root: Path) -> dict[str, Path]:
    """Relative posix path -> file, for every file in the mirror but the index itself."""
    if not root.is_dir():
        return {}
    return {
        rel: path
        for path in sorted(root.rglob("*"))
        if path.is_file() and (rel := path.relative_to(root).as_posix()) != INDEX_FILE
    }


def _load_index(root: Path) -> dict[str, dict]:
    """rel -> `{"local": …, "remote": …}` as of the last sync. Never raises.

    A missing or damaged index only costs the *history*, not the data: every file then
    looks like a first encounter, which compares the two copies for real.
    """
    try:
        data = json.loads((root / INDEX_FILE).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(rel): {"local": str(entry.get("local") or ""), "remote": str(entry.get("remote") or "")}
        for rel, entry in data.items()
        if isinstance(entry, dict)
    }


def _save_index(root: Path, index: dict[str, dict]) -> None:
    try:
        (root / INDEX_FILE).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    except OSError:  # pragma: no cover - a read-only mirror is already failing elsewhere
        pass


def _agreed(local: str, remote: str) -> dict:
    return {"local": local, "remote": remote}


def _remote_index(client: WebDAVClient) -> dict:
    return {info.rel: info for info in client.list_files()}


def pull(root: Path, options: dict) -> SyncResult:
    """Bring down every file the share has newer work in. Leaves local edits alone."""
    client = client_for(options)
    index = _load_index(root)
    local = _local_files(root)
    result = SyncResult(local=len(local))

    for rel, info in sorted(_remote_index(client).items()):
        result.remote += 1
        path = local.get(rel)
        body: bytes | None = None
        if path is not None:
            here = digest(path.read_bytes())
            known = index.get(rel)
            if known is None:
                # No agreement on record: the tokens are not comparable, so ask for the
                # bytes and settle it that way.
                body = client.get_file(rel)
                if digest(body) == here:
                    index[rel] = _agreed(here, info.etag)
                    continue
                if path.stat().st_mtime > info.modified + SKEW:
                    continue  # ours is the newer of two unrelated copies
            else:
                if known["remote"] == info.etag:
                    continue  # the share has not moved since last time — ours is the new work
                if known["local"] == here:
                    pass  # only the share moved: take it
                elif path.stat().st_mtime > info.modified + SKEW:
                    continue  # both changed: the tiebreak, and only here
        if body is None:
            body = client.get_file(rel)
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        if info.modified:
            os.utime(target, (info.modified, info.modified))
        index[rel] = _agreed(digest(body), info.etag)
        result.pulled.append(rel)

    _save_index(root, index)
    return result


def push(root: Path, options: dict) -> SyncResult:
    """Send up every file this mirror has newer work in. Leaves the share's newer alone."""
    client = client_for(options)
    index = _load_index(root)
    remote = _remote_index(client)
    local = _local_files(root)
    result = SyncResult(remote=len(remote), local=len(local))

    for rel, path in local.items():
        data = path.read_bytes()
        here = digest(data)
        info = remote.get(rel)
        if info is not None:
            known = index.get(rel)
            if known is None:
                if digest(client.get_file(rel)) == here:
                    index[rel] = _agreed(here, info.etag)
                    continue
                if info.modified > path.stat().st_mtime + SKEW:
                    continue  # theirs is the newer of two unrelated copies
            else:
                if known["local"] == here:
                    continue  # we have not moved since last time — theirs is the new work
                if known["remote"] == info.etag:
                    pass  # only we moved: send it
                elif info.modified > path.stat().st_mtime + SKEW:
                    continue  # both changed: the tiebreak, and only here
        index[rel] = _agreed(here, client.put_file(rel, data))
        result.pushed.append(rel)

    _save_index(root, index)
    return result


def sync(root: Path, options: dict) -> SyncResult:
    """Pull, then push. Raises `WebDAVError` — a sync that failed must not report success.

    Pull first so a file that is newer on the share is on disk before push looks at it,
    which is what stops the two halves from fighting over the same file.
    """
    root.mkdir(parents=True, exist_ok=True)
    down = pull(root, options)
    up = push(root, options)
    return SyncResult(pulled=down.pulled, pushed=up.pushed, remote=up.remote, local=up.local)
