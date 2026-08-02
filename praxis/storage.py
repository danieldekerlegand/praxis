#!/usr/bin/env python3
"""Where a user's own data lives — the one module that answers "on which disk?".

Praxis writes four kinds of thing, and only these four are the *user's*: the subjects
they define, the curricula generated for them, the notebooks (plus `<slug>.checks.json`)
constructed into them, and each learner's progress. The seed library under `notebooks/`
is not user data — it ships with the app and is read-only — so nothing here touches it.

Everything the user owns lives under **one root**, and this module is the only thing that
knows where that root is:

    <root>/subjects/<slug>/curriculum.json          the definition
    <root>/subjects/<slug>/<NN-module>/<topic>.ipynb        the tutorial
    <root>/subjects/<slug>/<NN-module>/<topic>.checks.json  its gate
    <root>/progress/<learner>.json                 what that learner has passed

`curriculum.subjects_dir()` and `praxis.progress.progress_dir()` are one-line delegates to
the two functions below, so every existing caller moved with the root the day this landed
and none of them had to learn about backends.

A **backend** is a `kind` plus the root it resolves to. Three ship:

    app     (default)  the desktop shell's own app-data directory — this computer
    drive              a folder the user picked, typically on a mounted disk
    cloud              an S3-compatible bucket, mirrored to a local working copy

They differ only in `_RESOLVERS` / `_AVAILABLE` (plus `_ON_SELECT` / `_SYNC` for the one
that has to talk to a network), which is the whole plug point: a new backend is a resolver
and an availability check, never a path computation in a caller.

The reason `cloud` still resolves to a *directory* is that every writer in this project
writes with `Path` — `nbformat.write`, `json.dump`, a `glob` over a module. So the cloud
backend keeps an ordinary storage root on disk and syncs it with the bucket
(`praxis/cloud.py`): the app works with the network down, and it is the sync that fails
loudly rather than a notebook save.

Which backend is active is the one piece of state that must *not* move with the data:
it is `storage.json` in `app_dir()`, alongside — never inside — the active root. Point the
app at an unplugged drive and it can still tell you so, because the config saying "that
drive" is on the internal disk.

Four environment overrides, in the order they win:

    PRAXIS_SUBJECTS_DIR / PRAXIS_PROGRESS_DIR   one leaf each (tests, and only tests)
    PRAXIS_DATA_DIR                             the `app` backend's root
    PRAXIS_APP_DIR                              the app directory itself — the desktop
                                                shell passes Tauri's `app_data_dir()` here
                                                so the Rust and Python sides agree

With no environment at all, `app_dir()` computes the same per-OS path Tauri would
(`APP_ID` is the bundle identifier), which is what lets the launcher be run by hand and
still see the data the app wrote.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# src-tauri/tauri.conf.json `identifier`. Keep the two in step: it is what makes the
# path this module computes and the one Tauri hands us the same directory.
APP_ID = "dev.praxis.app"

CONFIG_FILE = "storage.json"
CONFIG_VERSION = 1

DATA_DIRNAME = "data"
SUBJECTS_DIRNAME = "subjects"
PROGRESS_DIRNAME = "progress"

#: Where the `cloud` backend keeps its working copy, inside the app directory.
CLOUD_DIRNAME = "cloud"

DEFAULT_KIND = "app"

#: Option keys that are credentials, and are never returned to a client.
SECRET_HINTS = ("secret", "key", "password", "token")


class StorageError(RuntimeError):
    """A backend could not be resolved, or the resolved one cannot be used."""


# --- the app directory ------------------------------------------------------


def _platform_app_dir() -> Path:
    """The per-user app directory Tauri's `app_data_dir()` resolves to on this OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_ID
    if os.name == "nt":
        base = os.environ.get("APPDATA") or home / "AppData" / "Roaming"
        return Path(base) / APP_ID
    base = os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"
    return Path(base) / APP_ID


def app_dir() -> Path:
    """Where `storage.json` lives, and the parent of the default data root.

    `PRAXIS_APP_DIR` overrides it — the desktop shell sets it to Tauri's own
    `app_data_dir()`, and the test suite points it at a tmp dir so no test can write
    into a developer's real app data.
    """
    override = os.environ.get("PRAXIS_APP_DIR")
    return Path(override).expanduser() if override else _platform_app_dir()


def config_path() -> Path:
    return app_dir() / CONFIG_FILE


# --- a backend --------------------------------------------------------------


@dataclass(frozen=True)
class Backend:
    """One place the user's data can live: a kind, and the root it resolves to."""

    kind: str
    root: Path
    label: str
    detail: str = ""
    options: dict = field(default_factory=dict)

    @property
    def subjects(self) -> Path:
        return self.root / SUBJECTS_DIRNAME

    @property
    def progress(self) -> Path:
        return self.root / PROGRESS_DIRNAME

    def available(self) -> tuple[bool, str]:
        """`(usable now, why not)` — checked per request, never cached.

        A mounted drive can be pulled out between two calls, so "is this backend there"
        is a question with a fresh answer every time it is asked. For `cloud` this reaches
        the network; use `writable()` when all you need is "may I save a file".
        """
        return _AVAILABLE.get(self.kind, _local_available)(self)

    def writable(self) -> tuple[bool, str]:
        """The local half of `available()`: can this process write into the root, now?

        Cheap and never networked, because it is checked before **every** write the app
        makes. The two answers come apart exactly once, and usefully: a cloud backend with
        the network down is *not available* (you cannot sync) but *is writable* (the
        mirror is an ordinary directory), so a learner keeps working on a plane and the
        bucket catches up later.
        """
        check = _WRITABLE.get(self.kind) or _AVAILABLE.get(self.kind, _local_available)
        return check(self)

    def ensure(self) -> Path:
        """Create the root and its two leaves, or raise `StorageError` saying why not."""
        ok, why = self.available()
        if not ok:
            raise StorageError(why)
        for path in (self.root, self.subjects, self.progress):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StorageError(f"cannot write to {path}: {exc}") from exc
        return self.root

    def public_options(self) -> dict:
        """The options minus anything that looks like a credential."""
        return {
            k: v for k, v in self.options.items()
            if not any(hint in k.lower() for hint in SECRET_HINTS)
        }

    def to_dict(self) -> dict:
        ok, why = self.available()
        return {
            "kind": self.kind,
            "label": self.label,
            "root": str(self.root),
            "subjects": str(self.subjects),
            "progress": str(self.progress),
            "available": ok,
            "detail": why or self.detail,
            "options": self.public_options(),
        }


def _local_available(backend: Backend) -> tuple[bool, str]:
    """A directory on this machine: writable, or creatable inside an existing parent."""
    root = backend.root
    if root.is_dir():
        return (True, "") if os.access(root, os.W_OK) else (False, f"{root} is not writable")
    if root.exists():
        return False, f"{root} exists but is not a directory"
    parent = next((p for p in root.parents if p.exists()), None)
    if parent is None:
        return False, f"{root} does not exist and neither does any parent"
    if not os.access(parent, os.W_OK):
        return False, f"cannot create {root}: {parent} is not writable"
    return True, ""


def _resolve_app(options: dict) -> Backend:
    """The default: a `data/` directory inside the app's own app-data directory."""
    override = os.environ.get("PRAXIS_DATA_DIR")
    root = Path(override).expanduser() if override else app_dir() / DATA_DIRNAME
    return Backend(
        kind="app",
        root=root,
        label="app storage",
        detail="this computer, in the Praxis app-data directory",
        options=dict(options),
    )


# --- a folder the user picked, usually on a mounted disk --------------------


def _resolve_drive(options: dict) -> Backend:
    """A path the user chose in a folder picker. The path *is* the root, verbatim."""
    raw = str(options.get("path") or "").strip()
    root = Path(raw).expanduser() if raw else Path()
    return Backend(
        kind="drive",
        root=root,
        label="mounted drive",
        detail=f"a folder you chose: {root}" if raw else "no folder chosen yet",
        options=dict(options),
    )


def _drive_available(backend: Backend) -> tuple[bool, str]:
    """Stricter than a plain local path, and for one specific reason.

    `_local_available` walks up to the first ancestor that exists, which is right for the
    app's own root (its parents are ours to make) and quietly wrong for a drive: with the
    disk unplugged, `/Volumes/Backup/Praxis` has an existing ancestor — `/Volumes` — so a
    permissive check would happily recreate the folder **on the internal disk** and the
    user would go on working into a decoy that their drive never sees.

    So the *immediate* parent has to be there. It is the mount point, and its absence is
    exactly the question "is the drive plugged in?".
    """
    raw = str(backend.options.get("path") or "").strip()
    if not raw:
        return False, "no folder chosen — pick one to store your work on"
    root = backend.root
    parent = root.parent
    if not parent.is_dir():
        return False, f"{parent} is not there — is the drive mounted?"
    if root.exists() and not root.is_dir():
        return False, f"{root} exists but is not a directory"
    target = root if root.is_dir() else parent
    if not os.access(target, os.W_OK):
        return False, f"{target} is not writable"
    return True, ""


# --- an S3-compatible bucket, mirrored locally ------------------------------


def _resolve_cloud(options: dict) -> Backend:
    """The bucket's working copy: a real directory, kept in step by `praxis.cloud.sync`."""
    from praxis import cloud

    root = app_dir() / CLOUD_DIRNAME / cloud.mirror_name(options)
    bucket = str(options.get("bucket") or "").strip()
    where = f"s3://{bucket}/{cloud.prefix_for(options)}" if bucket else "no bucket configured"
    return Backend(
        kind="cloud",
        root=root,
        label="cloud storage",
        detail=f"{where} — mirrored at {root}",
        options=dict(options),
    )


def _cloud_available(backend: Backend) -> tuple[bool, str]:
    """Can we talk to the bucket right now? The mirror on disk is a separate question.

    A `False` here means "you cannot sync", not "your work is gone" — the mirror is a
    normal directory and the app keeps writing to it offline.
    """
    from praxis import cloud

    if not str(backend.options.get("bucket") or "").strip():
        return False, "no bucket configured"
    return cloud.reachable(backend.options)


def _cloud_on_select(backend: Backend) -> None:
    """Selecting a bucket pulls it down, so a second machine sees the work already there."""
    from praxis import cloud
    from praxis.s3 import S3Error

    try:
        cloud.pull(backend.root, backend.options)
    except S3Error as exc:
        raise StorageError(f"could not read the bucket: {exc}") from exc


def _cloud_sync(backend: Backend) -> dict:
    from praxis import cloud
    from praxis.s3 import S3Error

    try:
        return cloud.sync(backend.root, backend.options).to_dict()
    except S3Error as exc:
        raise StorageError(f"sync failed: {exc}") from exc


#: kind -> resolver. Extend to add a backend; every caller keeps working unchanged.
_RESOLVERS: dict[str, Callable[[dict], Backend]] = {
    "app": _resolve_app,
    "drive": _resolve_drive,
    "cloud": _resolve_cloud,
}

#: kind -> availability check. Defaults to `_local_available` for anything path-shaped.
_AVAILABLE: dict[str, Callable[[Backend], tuple[bool, str]]] = {
    "drive": _drive_available,
    "cloud": _cloud_available,
}

#: kind -> the cheap local "can I write here" check, when it differs from `_AVAILABLE`.
#: Only a backend whose root is a mirror needs an entry: the cloud one is writable while
#: the bucket is unreachable, which is the whole reason the mirror exists.
_WRITABLE: dict[str, Callable[[Backend], tuple[bool, str]]] = {"cloud": _local_available}

#: kind -> what to do once this backend has been created and is about to become active.
_ON_SELECT: dict[str, Callable[[Backend], None]] = {"cloud": _cloud_on_select}

#: kind -> a two-way reconcile with wherever the real copy lives, for backends that have
#: a "there" distinct from their root. A backend absent here is already in one place.
_SYNC: dict[str, Callable[[Backend], dict]] = {"cloud": _cloud_sync}

#: kind -> the options it takes, as `(key, label, required, secret)`. One source of truth
#: for the settings form: the UI renders this rather than hardcoding a second copy.
FIELDS: dict[str, tuple[tuple[str, str, bool, bool], ...]] = {
    "app": (),
    "drive": (("path", "folder", True, False),),
    "cloud": (
        ("endpoint", "endpoint URL", True, False),
        ("bucket", "bucket", True, False),
        ("prefix", "prefix (optional)", False, False),
        ("region", "region", False, False),
        ("access_key_id", "access key ID", False, False),
        ("secret_access_key", "secret access key", False, True),
    ),
}

#: kind -> one sentence for the settings form, so the UI ships no copy of its own.
BLURBS: dict[str, str] = {
    "app": "This computer, in the Praxis app-data directory. Private, and needs no setup.",
    "drive": "A folder you choose — an external disk, a network share, a synced folder. "
             "Portable: unplug it and your work goes with you.",
    "cloud": "An S3-compatible bucket (AWS, MinIO, R2, B2). Praxis keeps a working copy "
             "on this computer so it still runs offline, and syncs it with the bucket.",
}


def register_backend(
    kind: str,
    resolver: Callable[[dict], Backend],
    available: Callable[[Backend], tuple[bool, str]] | None = None,
    on_select: Callable[[Backend], None] | None = None,
    sync: Callable[[Backend], dict] | None = None,
    writable: Callable[[Backend], tuple[bool, str]] | None = None,
) -> None:
    """Plug a backend in. `resolver` turns this kind's saved options into a `Backend`."""
    _RESOLVERS[kind] = resolver
    if available is not None:
        _AVAILABLE[kind] = available
    if writable is not None:
        _WRITABLE[kind] = writable
    if on_select is not None:
        _ON_SELECT[kind] = on_select
    if sync is not None:
        _SYNC[kind] = sync


def kinds() -> list[str]:
    """Every registered backend kind, the default first — what the UI offers."""
    rest = sorted(k for k in _RESOLVERS if k != DEFAULT_KIND)
    return [DEFAULT_KIND, *rest]


def resolve(kind: str, options: dict | None = None) -> Backend:
    """A `Backend` for `kind`, or the default one when the kind is unknown.

    Unknown never raises: a config written by a newer version, or hand-edited, must not
    make the app unopenable — it falls back to app storage and says so in `detail`.
    """
    options = dict(options or {})
    resolver = _RESOLVERS.get(str(kind or ""))
    if resolver is None:
        fallback = _resolve_app(options)
        return Backend(
            kind=fallback.kind,
            root=fallback.root,
            label=fallback.label,
            detail=f"unknown storage backend {kind!r} — using app storage",
            options=fallback.options,
        )
    return resolver(options)


# --- the config that says which backend is active ---------------------------


def default_config() -> dict:
    return {"version": CONFIG_VERSION, "active": DEFAULT_KIND, "backends": {}, "updated": ""}


def load_config() -> dict:
    """The stored selection, or the default. Never raises — see `progress.load_progress`.

    A config that is missing, unreadable, or from a version this build doesn't know reads
    as "app storage", so a corrupt file costs the user their *selection*, never their data.
    """
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return default_config()
    if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
        return default_config()
    if not isinstance(data.get("backends"), dict):
        data["backends"] = {}
    return data


def save_config(config: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config["version"] = CONFIG_VERSION
    config["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(config, indent=2) + "\n")
    # A cloud backend's options include its secret key, so this file is owner-only.
    # Best effort: a filesystem without POSIX modes (a FAT drive, Windows) is not an
    # error, and the config is not where the user's work is.
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return path


def active_backend() -> Backend:
    """The backend the user selected, resolved fresh from `storage.json`."""
    config = load_config()
    kind = str(config.get("active") or DEFAULT_KIND)
    options = config.get("backends", {}).get(kind)
    return resolve(kind, options if isinstance(options, dict) else {})


def stored_options(kind: str) -> dict:
    """This kind's saved options, whether or not it is the active backend."""
    saved = load_config().get("backends", {}).get(kind)
    return dict(saved) if isinstance(saved, dict) else {}


def merge_options(kind: str, options: dict | None) -> dict:
    """Incoming form values over the stored ones, keeping secrets the client never saw.

    `Backend.public_options()` strips credentials on the way out, so the settings form
    cannot echo the secret it is editing back to us. A blank secret therefore has to mean
    "leave it alone" rather than "erase it" — otherwise switching a bucket's prefix would
    silently log the user out of it. Every other field is taken exactly as sent, blank
    included, so clearing one still works.
    """
    merged = stored_options(kind)
    secrets = {key for key, _, _, secret in FIELDS.get(kind, ()) if secret}
    for key, value in dict(options or {}).items():
        if key in secrets and not str(value or "").strip():
            continue
        merged[key] = value
    return merged


def select_backend(kind: str, options: dict | None = None) -> Backend:
    """Make `kind` the active backend, create its directories, and bring it up to date.

    Verified before it is stored: an unusable backend is rejected with `StorageError` and
    the previous selection survives, so a mistyped path or an unplugged drive can't strand
    a user's data. `_ON_SELECT` runs last (the cloud backend pulls the bucket down there),
    and a failure in it is also a rejection — switching to a backend we could not read
    would show the user an empty library and invite them to fill it.
    """
    if kind not in _RESOLVERS:
        raise StorageError(f"unknown storage backend {kind!r} — one of {kinds()}")
    backend = resolve(kind, merge_options(kind, options))
    backend.ensure()
    hook = _ON_SELECT.get(backend.kind)
    if hook is not None:
        hook(backend)
    config = load_config()
    config["active"] = backend.kind
    config.setdefault("backends", {})[backend.kind] = dict(backend.options)
    save_config(config)
    return backend


def sync_active() -> dict:
    """Reconcile the active backend with wherever its real copy lives.

    Only `cloud` has somewhere else to be; for the others this is a no-op that says so,
    rather than an error — "sync" is a question the UI can ask of any backend.
    """
    backend = active_backend()
    hook = _SYNC.get(backend.kind)
    if hook is None:
        return {"kind": backend.kind, "synced": False,
                "detail": f"{backend.label} is already in one place — nothing to sync"}
    ok, why = backend.available()
    if not ok:
        raise StorageError(why)
    return {"kind": backend.kind, "synced": True, **hook(backend)}


# --- what every other module actually calls ---------------------------------


def data_root() -> Path:
    return active_backend().root


def subjects_dir() -> Path:
    """Where generated subjects live. `PRAXIS_SUBJECTS_DIR` relocates just this leaf."""
    override = os.environ.get("PRAXIS_SUBJECTS_DIR")
    return Path(override) if override else active_backend().subjects


def progress_dir() -> Path:
    """Where learner progress lives. `PRAXIS_PROGRESS_DIR` relocates just this leaf."""
    override = os.environ.get("PRAXIS_PROGRESS_DIR")
    return Path(override) if override else active_backend().progress


def kind_info(kind: str) -> dict:
    """What the settings form needs to offer one backend: its fields and their values.

    The saved options come back through `Backend.public_options()`, so a stored secret is
    reported as configured (`"set": true`) without ever being sent — see `merge_options`
    for the other half of that: a blank secret field means "keep the one you have".
    """
    saved = stored_options(kind)
    return {
        "kind": kind,
        "label": resolve(kind, saved).label,
        "blurb": BLURBS.get(kind, ""),
        "fields": [
            {"key": key, "label": label, "required": required, "secret": secret,
             "value": "" if secret else str(saved.get(key, "") or ""),
             "set": bool(str(saved.get(key, "") or "").strip())}
            for key, label, required, secret in FIELDS.get(kind, ())
        ],
    }


def describe() -> dict:
    """The whole storage picture, for `GET /api/storage` and the app's footer."""
    backend = active_backend()
    return {
        **backend.to_dict(),
        "appDir": str(app_dir()),
        "config": str(config_path()),
        # The effective paths, which the env overrides can move off the backend root.
        "subjects": str(subjects_dir()),
        "progress": str(progress_dir()),
        "kinds": kinds(),
        "backends": [kind_info(kind) for kind in kinds()],
        "syncable": backend.kind in _SYNC,
    }


def main() -> None:  # pragma: no cover - a convenience for "where is my data?"
    print(json.dumps(describe(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
