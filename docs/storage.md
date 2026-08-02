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

Three backends ship. They differ only in where the root is; the layout above and every
line of code that writes into it are identical across all three.

| backend | root | |
|---|---|---|
| `app` *(default)* | the app-data directory, `data/` | this computer, per user |
| `drive` | the folder you picked, verbatim | an external disk, a share, a synced folder |
| `cloud` | a mirror in the app-data directory, `cloud/<bucket>[-<prefix>]/` | synced with an S3-compatible bucket |

Choose one in the app under **storage**, or from a terminal:

```bash
python -c 'from praxis import storage; storage.select_backend("drive", {"path": "/Volumes/Backup/Praxis"})'
```

Switching changes **where Praxis looks**. It never copies, moves or deletes anything: the
root you leave keeps everything that was in it, and is exactly as you left it if you switch
back. Moving your work between backends is `cp -R` on the one directory in the layout above.

### `drive` — a folder you picked

The path you choose *is* the root; Praxis creates `subjects/` and `progress/` in it. The
availability check is deliberately stricter than for the other backends: the folder's
**immediate parent** must exist. That parent is the mount point, and its absence is the
question "is the drive plugged in?".

The looser check — walk up to the first ancestor that exists — is the one that loses data.
With the disk unplugged, `/Volumes/Backup/Praxis` still has an existing ancestor
(`/Volumes`), so a permissive check would recreate the folder on the internal disk and you
would fill a decoy your drive never sees. Instead the launcher answers **503** to every
write while the drive is missing, saying which path it is looking for.

### `cloud` — an S3-compatible bucket

Everything in Praxis writes with ordinary file calls, so the cloud backend is a **local
mirror plus a sync** (`praxis/cloud.py`), not a filesystem over HTTP:

* the mirror is a normal storage root, so the app works with the network down;
* selecting the bucket pulls it down, which is how a second machine picks up your work;
* **Sync now** (or `POST /api/storage/sync`) pushes what you changed and pulls what
  changed elsewhere. A sync that could not reach the bucket is an error, never a
  silent no-op.

Per file, the side that *changed* wins — `.praxis-sync.json` in the mirror records the
digest both sides agreed on last time, so "who has the new work" is answered by content,
not by clocks. Timestamps only break a true conflict (both sides edited since the last
sync). **A sync never deletes:** a cleared bucket cannot empty your disk, and a cleared
mirror cannot empty the bucket.

It takes any S3-compatible endpoint — AWS, MinIO, Cloudflare R2, Backblaze B2 — using
path-style addressing and single-part uploads (`praxis/s3.py`, ~250 lines of `urllib` and
`hmac`; no boto3, because the core stays dependency-light). Options:

| option | |
|---|---|
| `endpoint` | scheme and host, e.g. `https://s3.us-east-1.amazonaws.com` |
| `bucket` | the bucket name |
| `prefix` | optional key prefix, so one bucket can hold several things |
| `region` | defaults to `us-east-1` |
| `access_key_id` / `secret_access_key` | omit both for an unauthenticated endpoint |

### The app-data directory

It is the one the desktop shell owns, and it is per-OS:

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
app's footer can be shown to anyone. The settings form is therefore never sent the secret
it is editing, which is why a **blank secret field means "keep the stored one"** rather
than "erase it" (`storage.merge_options`); every other field is taken exactly as typed,
blank included. `storage.json` itself is written `0600` — it holds that secret in the
clear, so treat it as you would `~/.aws/credentials`.

## The API

| | |
|---|---|
| `GET /api/storage` | the active backend, its root, whether it's there, and every backend's form |
| `POST /api/storage` | `{kind, options}` — switch. **400** with the reason if unusable; the old selection stands |
| `POST /api/storage/sync` | push/pull the cloud mirror. **503** with the reason if the bucket is unreachable |

Every *other* write in the launcher is refused with **503** while the active backend is
unwritable — one middleware in `launcher/app.py`, so no endpoint can forget. `/api/storage`
is exempt, because pointing Praxis somewhere else is the fix.

The check there is `Backend.writable()` (local, cheap), not `Backend.available()` (which
reaches the bucket). They come apart exactly once, and usefully: a cloud backend with the
network down is *unavailable* — you cannot sync — but perfectly *writable*, because its
root is a mirror on this disk. Going offline must not stop a learner answering a question.

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

def resolve_tape(options: dict) -> storage.Backend:
    return storage.Backend(kind="tape", root=Path(options["path"]), label="tape robot")

storage.register_backend("tape", resolve_tape)
```

Nothing else changes. `curriculum.subjects_dir()` and `praxis.progress.progress_dir()`
are one-line delegates to this module, so every caller that already writes a subject or
records an outcome follows the new root the moment it is selected. That is what
`test_a_registered_backend_needs_no_change_to_any_caller` is there to hold: adding a
backend is never a path computation in a caller.

Four more hooks, all optional, all keyed by kind — `_AVAILABLE` (is it there?),
`_WRITABLE` (may I write, cheaply and locally — only needed when it differs), `_ON_SELECT`
(what to do on becoming active; the cloud backend pulls) and `_SYNC` (reconcile with a copy
that lives elsewhere). Add the kind to `storage.FIELDS` and `storage.BLURBS` and the
settings form in the app grows the new option boxes on its own — the UI renders whatever
`GET /api/storage` describes and holds no list of its own.

`select_backend()` resolves, checks, **creates** and then runs `_ON_SELECT` before it
stores the choice — an unusable backend is rejected at any of those steps and the previous
selection survives, so a mistyped path or an unreachable bucket can't strand your work.

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
