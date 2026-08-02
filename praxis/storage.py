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

A **backend** is a `kind` plus the root it resolves to. `app` (the default) resolves to the
desktop shell's own app-data directory, so a user who never opens the settings still gets
durable, per-user storage. `drive` and `cloud` plug in through `_RESOLVERS` / `_AVAILABLE`
— a new backend is a resolver and an availability check, not a change to any caller.

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
        is a question with a fresh answer every time it is asked.
        """
        return _AVAILABLE.get(self.kind, _local_available)(self)

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


#: kind -> resolver. Extend to add a backend; every caller keeps working unchanged.
_RESOLVERS: dict[str, Callable[[dict], Backend]] = {"app": _resolve_app}

#: kind -> availability check. Defaults to `_local_available` for anything path-shaped.
_AVAILABLE: dict[str, Callable[[Backend], tuple[bool, str]]] = {}


def register_backend(
    kind: str,
    resolver: Callable[[dict], Backend],
    available: Callable[[Backend], tuple[bool, str]] | None = None,
) -> None:
    """Plug a backend in. `resolver` turns this kind's saved options into a `Backend`."""
    _RESOLVERS[kind] = resolver
    if available is not None:
        _AVAILABLE[kind] = available


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
    return path


def active_backend() -> Backend:
    """The backend the user selected, resolved fresh from `storage.json`."""
    config = load_config()
    kind = str(config.get("active") or DEFAULT_KIND)
    options = config.get("backends", {}).get(kind)
    return resolve(kind, options if isinstance(options, dict) else {})


def select_backend(kind: str, options: dict | None = None) -> Backend:
    """Make `kind` the active backend and create its directories.

    Verified before it is stored: an unusable backend is rejected with `StorageError` and
    the previous selection survives, so a mistyped path can't strand a user's data.
    """
    if kind not in _RESOLVERS:
        raise StorageError(f"unknown storage backend {kind!r} — one of {kinds()}")
    backend = resolve(kind, options)
    backend.ensure()
    config = load_config()
    config["active"] = backend.kind
    config.setdefault("backends", {})[backend.kind] = dict(backend.options)
    save_config(config)
    return backend


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
    }


def main() -> None:  # pragma: no cover - a convenience for "where is my data?"
    print(json.dumps(describe(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
