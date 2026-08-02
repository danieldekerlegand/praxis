# Storage — where your work is kept

Praxis writes four kinds of thing, and all four belong to **you**: the subjects you
define, the curricula generated for them, the tutorials constructed into them (notebooks
plus their knowledge checks), and each learner's progress. The seed library under
`notebooks/` is not yours in that sense — it ships with the app and is never written to,
so nothing described here touches it.

All four live under **one root**, and one module knows where that root is:
[`praxis/storage.py`](../praxis/storage.py).

## The layout

```
<root>/
├── subjects/
│   └── <slug>/
│       ├── curriculum.json                 the subject: modules → topics
│       └── <NN-module>/
│           ├── <topic>.ipynb               the tutorial
│           └── <topic>.checks.json         its gate — the answer key lives here,
│                                           beside the notebook, never inside it
└── progress/
    └── <learner>.json                      every graded outcome, answers verbatim
```

Copying that one directory copies everything you have built and everything you have
passed. Nothing else is needed, and nothing in it points back at where it came from.

## Where the root is

| backend | root | |
|---|---|---|
| `app` *(default)* | the app-data directory, `data/` | this computer, per user |

`drive` (a mounted disk) and `cloud` (an S3-compatible location) plug into the same
abstraction — see `_RESOLVERS` in `praxis/storage.py`.

The app-data directory is the one the desktop shell owns, and it is per-OS:

| | |
|---|---|
| macOS | `~/Library/Application Support/dev.praxis.app` |
| Windows | `%APPDATA%\dev.praxis.app` |
| Linux | `$XDG_DATA_HOME/dev.praxis.app` (else `~/.local/share/dev.praxis.app`) |

Tauri hands the shell that path and the shell passes it to the Python side as
`PRAXIS_APP_DIR`. With no environment at all, `praxis/storage.py` computes the same path
from the same bundle identifier — which is what lets you run `praxis-launch` in a
terminal and see exactly the data the app wrote.

To find it on any machine:

```bash
python -m praxis.storage        # the active backend, its root, and whether it's there
curl localhost:8000/api/storage # the same thing, as the app reads it
```

## The selection is not stored with the data

Which backend is active lives in `storage.json` in the **app directory** — alongside the
default root, never inside the active one:

```
<app dir>/storage.json     {"version": 1, "active": "app", "backends": {...}}
<app dir>/data/            the `app` backend's root
```

That separation is the point: point Praxis at a drive, unplug the drive, and the app can
still start and tell you which drive it is looking for, because the note saying so is on
the internal disk. A `storage.json` that is missing, unreadable or from a newer version
reads as "app storage" — a corrupt config costs you your *selection*, never your data.

Credentials in a backend's options (an S3 secret, say) are stripped by
`Backend.public_options()` before anything reaches a client, so `/api/storage` and the
app's footer can be shown to anyone.

## Environment overrides

In the order they win:

| variable | moves |
|---|---|
| `PRAXIS_SUBJECTS_DIR` | just `subjects/` — the test suite's escape hatch |
| `PRAXIS_PROGRESS_DIR` | just `progress/` — likewise |
| `PRAXIS_DATA_DIR` | the `app` backend's root (a portable checkout, a scratch run) |
| `PRAXIS_APP_DIR` | the app directory itself, config and all |

The test suite sets `PRAXIS_APP_DIR` to a temp directory for **every** test
(`tests/conftest.py`), so no test can write into a developer's real storage even if it
forgets the finer-grained fixtures.

## Adding a backend

A backend is a resolver and, if it isn't a plain path, an availability check:

```python
from praxis import storage

def resolve_drive(options: dict) -> storage.Backend:
    return storage.Backend(kind="drive", root=Path(options["path"]), label="mounted drive")

storage.register_backend("drive", resolve_drive)
```

Nothing else changes. `curriculum.subjects_dir()` and `praxis.progress.progress_dir()`
are one-line delegates to this module, so every caller that already writes a subject or
records an outcome follows the new root the moment it is selected.

`select_backend()` resolves, checks and **creates** the layout before it stores the
choice — an unusable backend is rejected and the previous selection survives, so a
mistyped path can't strand your work.

## Upgrading from an earlier checkout

Before storage backends existed, subjects were written to `notebooks/subjects/` and
progress to `.praxis/progress/` inside the repo. Those are ordinary directories: move
them under the new root and they are picked up as they are.

```bash
ROOT=$(python -c 'from praxis import storage; print(storage.data_root())')
mkdir -p "$ROOT"
mv notebooks/subjects "$ROOT"/subjects
mv .praxis/progress  "$ROOT"/progress
```
