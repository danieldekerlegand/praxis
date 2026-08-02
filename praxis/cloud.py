#!/usr/bin/env python3
"""The cloud backend's working copy, and how it gets to and from the bucket.

Every other part of Praxis writes with `Path` — `nbformat.write`, `json.dump`, a `glob`
for the notebooks in a module. Making a bucket the storage root would mean rewriting all
of them, and the whole point of `praxis/storage.py` is that adding a backend changes *no*
caller. So the cloud backend is a **local mirror plus a sync**, the way every file-syncing
app that isn't a filesystem driver works:

    <app dir>/cloud/<bucket>[-<prefix>]/     the mirror — an ordinary storage root
    s3://<bucket>/<prefix>/subjects/…        the same tree, as objects

The mirror is what `subjects_dir()` and `progress_dir()` resolve to, so the app is fully
usable with the network down; what fails when the bucket is unreachable is the *sync*, and
it fails out loud (`S3Error`) rather than pretending. `pull()` runs when the backend is
selected, so a second machine picking the same bucket gets the work that is already there.

The merge rule is per file, and it is decided by *which side changed*, not by which side
has the later timestamp. `sync()` records the digest both sides agreed on last time
(`.praxis-sync.json`, in the mirror), so the ordinary case is unambiguous: exactly one
side differs from that digest, and that side is the one with the new work. Timestamps are
the tiebreak for the genuine conflict — both sides edited since the last sync — and
nothing else, because they are the part that lies. A clock a few seconds off, or an edit
made in the same second as the sync before it, would otherwise be enough to overwrite a
notebook the user had just finished.

A sync **never deletes**. A bucket that has lost an object cannot take a notebook off your
disk, and a mirror you cleared cannot empty the bucket. Removing something is a thing the
user does in one place, on purpose, not something a background copy infers.

`ETag` is the object's MD5 (single-part PUTs only — see `praxis/s3.py`), which is what
lets "has this file changed?" be answered without a download.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from praxis.s3 import S3Client, S3Error, md5_of

#: What both sides agreed on last time, per file. Lives in the mirror (copy the folder and
#: the sync state comes with it) and is the one path never synced.
INDEX_FILE = ".praxis-sync.json"

#: Only consulted for a true conflict — both sides changed since the last sync — and then
#: only as a margin: a difference smaller than this is not evidence of anything, so the
#: local copy stands. Object stores stamp in whole seconds; local mtimes are finer.
SKEW = 2.0

#: Option keys a cloud backend understands. `describe()` offers these to the UI.
OPTION_KEYS = (
    "endpoint",
    "bucket",
    "prefix",
    "region",
    "access_key_id",
    "secret_access_key",
    "session_token",
)


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


def client_for(options: dict, timeout: float | None = None) -> S3Client:
    """An `S3Client` for a cloud backend's saved options. Raises `S3Error` if unusable."""
    kwargs = {
        "endpoint": str(options.get("endpoint") or ""),
        "bucket": str(options.get("bucket") or ""),
        "access_key_id": str(options.get("access_key_id") or ""),
        "secret_access_key": str(options.get("secret_access_key") or ""),
        "region": str(options.get("region") or "us-east-1"),
        "session_token": str(options.get("session_token") or ""),
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return S3Client(**kwargs)


def prefix_for(options: dict) -> str:
    """The key prefix, normalised to `''` or `'something/'`."""
    prefix = str(options.get("prefix") or "").strip().strip("/")
    return f"{prefix}/" if prefix else ""


def mirror_name(options: dict) -> str:
    """A stable, filesystem-safe directory name for one bucket+prefix pair."""
    parts = [str(options.get("bucket") or "bucket"), prefix_for(options).strip("/")]
    raw = "-".join(p for p in parts if p)
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in raw).strip("-") or "bucket"


def reachable(options: dict, timeout: float = 5.0) -> tuple[bool, str]:
    """`(can we talk to the bucket right now, why not)`. Never raises.

    Called from `Backend.available()`, so it must answer quickly and it must answer
    *now* — a bucket is exactly the kind of root that is there on one request and gone on
    the next.
    """
    try:
        client = client_for(options, timeout=timeout)
    except S3Error as exc:
        return False, str(exc)
    try:
        client.head_bucket()
    except S3Error as exc:
        # `exc` already names the endpoint, so this says which *bucket* was wanted.
        return False, f"cannot reach s3://{client.bucket}/{prefix_for(options)} — {exc}"
    return True, ""


# --- the mirror -------------------------------------------------------------


def _local_files(root: Path) -> dict[str, Path]:
    """Relative posix path -> file, for every file in the mirror but the index itself."""
    if not root.is_dir():
        return {}
    return {
        rel: path
        for path in sorted(root.rglob("*"))
        if path.is_file() and (rel := path.relative_to(root).as_posix()) != INDEX_FILE
    }


def _load_index(root: Path) -> dict[str, str]:
    """rel -> the digest both sides had at the end of the last sync. Never raises.

    A missing or damaged index only costs the *history*, not the data: every file then
    looks like a first encounter, which falls back to the timestamp tiebreak.
    """
    try:
        data = json.loads((root / INDEX_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save_index(root: Path, index: dict[str, str]) -> None:
    try:
        (root / INDEX_FILE).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    except OSError:  # pragma: no cover - a read-only mirror is already failing elsewhere
        pass


def _remote_index(client: S3Client, prefix: str) -> dict:
    """rel -> object, for everything under the prefix. Directory markers dropped."""
    found = {}
    for obj in client.list_objects(prefix=prefix):
        if not obj.key.startswith(prefix):
            continue
        rel = obj.key[len(prefix):]
        if rel and not rel.endswith("/"):
            found[rel] = obj
    return found


def pull(root: Path, options: dict) -> SyncResult:
    """Bring down every file the bucket has newer work in. Leaves local edits alone."""
    client = client_for(options)
    prefix = prefix_for(options)
    index = _load_index(root)
    local = _local_files(root)
    result = SyncResult(local=len(local))

    for rel, obj in sorted(_remote_index(client, prefix).items()):
        result.remote += 1
        path = local.get(rel)
        if path is not None:
            here = md5_of(path.read_bytes())
            if here == obj.etag:
                index[rel] = here  # already agreed; just remember that we agreed
                continue
            known = index.get(rel)
            if known == obj.etag:
                continue  # the bucket has not moved since last time — ours is the new work
            if known != here and path.stat().st_mtime > obj.modified + SKEW:
                continue  # both changed: the tiebreak, and only here
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(client.get_object(obj.key))
        if obj.modified:
            os.utime(target, (obj.modified, obj.modified))
        index[rel] = obj.etag
        result.pulled.append(rel)

    _save_index(root, index)
    return result


def push(root: Path, options: dict) -> SyncResult:
    """Send up every file this mirror has newer work in. Leaves the bucket's newer alone."""
    client = client_for(options)
    prefix = prefix_for(options)
    index = _load_index(root)
    remote = _remote_index(client, prefix)
    local = _local_files(root)
    result = SyncResult(remote=len(remote), local=len(local))

    for rel, path in local.items():
        here = md5_of(path.read_bytes())
        obj = remote.get(rel)
        if obj is not None:
            if here == obj.etag:
                index[rel] = here
                continue
            known = index.get(rel)
            if known == here:
                continue  # we have not moved since last time — the bucket's is the new work
            if known != obj.etag and obj.modified > path.stat().st_mtime + SKEW:
                continue  # both changed: the tiebreak, and only here
        client.put_object(prefix + rel, path.read_bytes())
        index[rel] = here
        result.pushed.append(rel)

    _save_index(root, index)
    return result


def sync(root: Path, options: dict) -> SyncResult:
    """Pull, then push. Raises `S3Error` — a sync that failed must not report success.

    Pull first so a file that is newer in the bucket is on disk before push looks at it,
    which is what stops the two halves from fighting over the same file.
    """
    root.mkdir(parents=True, exist_ok=True)
    down = pull(root, options)
    up = push(root, options)
    return SyncResult(
        pulled=down.pulled, pushed=up.pushed, remote=up.remote, local=up.local
    )
