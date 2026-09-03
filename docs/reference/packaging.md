# Packaging Praxis

> **Status:** Current · **Updated:** 2026-09-03 · **Owner:** praxis

Two distributable shapes come out of this repo, and both wrap the same Python core:

| Target | What it is | Built with |
|--------|------------|------------|
| **Desktop bundle** | A native app (`.app`/`.dmg`, `.msi`/`.exe`, `.deb`/`.AppImage`) around the Tauri shell | `tauri build` |
| **Web build** (optional) | `ui/dist` served by any static server, talking to a hand-started `praxis-launch` | `npm run build` + `praxis-launch` |

The shell is not the product — `launcher/app.py` and the notebook core are. Both targets
start from the same `ui/dist`, and both browse the same launcher API.

A bundle also carries the **JupyterLite site** a learner runs tutorials in — static
JupyterLab on a Pyodide kernel, so reading and running a notebook needs no local Python at
all. It is built by `scripts/build-jupyterlite.sh` into `src-tauri/resources/jupyterlite`
(untracked, like the embedded runtime below) and `make bundle` depends on it. See
[JupyterLite — the tutorial runtime in the browser](jupyterlite.md) and
[The tutorial runtime in the bundle](#the-tutorial-runtime-in-the-bundle) below.

## Prerequisites

- **Rust** (stable, ≥ 1.77.2) and **Node 20+** with npm.
- **Python 3.10+** with the launch extra — the shell *runs* the Python core, and a build
  either embeds one or discovers one on the machine
  (see [The Python runtime in the bundle](#the-python-runtime-in-the-bundle)).
- **uv** — only for an embedded bundle: it is what fetches the relocatable interpreter
  (`scripts/embed-python.sh`). Not needed to build or run anything else.
- macOS: Xcode Command Line Tools (`xcode-select --install`). Full Xcode is not required
  for an unsigned build.
- Linux: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev
  patchelf` (the same list `.github/workflows/ci.yml` installs).
- Windows: WebView2 runtime (present on Windows 11; the NSIS installer can bootstrap it).

The Tauri CLI ships as a dev dependency of the frontend, so there is nothing to install
globally.

## Desktop bundle

Run from the **repo root** — the CLI finds `src-tauri/` by walking up from the working
directory, so the `--prefix` only tells npm where the CLI lives:

```bash
npm --prefix ui ci      # once
make bundle             # JupyterLite site, then release build + bundle
```

`make bundle` is the command to use rather than the bare CLI: it builds the JupyterLite
site first and adds the overlay config that copies it into the bundle
([below](#the-tutorial-runtime-in-the-bundle)). The bare form still works and produces a
shell with no in-browser runtime:

```bash
npm --prefix ui exec -- tauri build     # release build + bundle, site not included
```

`tauri build` runs `beforeBuildCommand` (`npm --prefix ../ui run build`) itself, so the
frontend is rebuilt and embedded — no stale `ui/dist` can sneak into a release.

Output lands under `src-tauri/target/release/bundle/`:

| OS | Artifacts (under `bundle/`) |
|----|-----------|
| **macOS** | `macos/Praxis.app` · `dmg/Praxis_<version>_<arch>.dmg` — verified here: `Praxis_0.1.0_aarch64.dmg` |
| **Windows** | `msi/*.msi` · `nsis/*-setup.exe` |
| **Linux** | `deb/*.deb` · `rpm/*.rpm` · `appimage/*.AppImage` |

Bundles are **not cross-compiled** — each OS builds its own, so the Windows and Linux
rows are the directories `tauri build` writes there, not builds this repo has produced.
`bundle.targets` is `"all"` in `src-tauri/tauri.conf.json`, so each platform emits
everything it can; narrow a run with `--bundles`, e.g. `tauri build --bundles app` for a
macOS `.app` without the DMG step.

The CI job `bundle-macos` in `.github/workflows/ci.yml` (manual, `workflow_dispatch`)
runs the release script below and uploads the `.app` and `.dmg` as artifacts.

### One version, three manifests

The app version is declared in three files, and nothing derives one from another:

| File | What carries it |
|------|-----------------|
| `src-tauri/tauri.conf.json` | the app version, and the name of the `.dmg` (`Praxis_<version>_<arch>.dmg`) |
| `pyproject.toml` | the Python core, which the bundle *runs* rather than contains |
| `ui/package.json` | the frontend embedded into the shell |

So **bumping a release means editing all three in the same commit** — otherwise a `.dmg`
called 0.2.0 ships a 0.1.0 core, and there is no build step that would notice.

`scripts/check-versions.py` is the check, and it is wired in twice:

```bash
scripts/check-versions.py     # prints the agreed version, or names the files that disagree
```

- **Every PR** that touches one of the three manifests (or `scripts/`, or any Python) runs
  it — `tests/test_packaging.py` asserts on it, so it rides in CI's existing `python`
  job. `.github/workflows/ci.yml` and `.chief/verify.sh` scope those files into that job
  for exactly this reason — the version check rides an existing job rather than adding
  one.
- **Every release**: `scripts/bundle-macos.sh` runs it before building and refuses (exit
  2) a mismatch, so the disagreement costs a second rather than a ten-minute build. The
  plan line is followed by `bundle: version <x> in step across …`.

A mismatch prints every manifest and the version it declares, which is the fix:

```
version: the manifests disagree — a release must carry one version.
  src-tauri/tauri.conf.json  0.2.0
  pyproject.toml             0.1.0
  ui/package.json            0.1.0
fix: set the same version in each file above, then re-run this check.
```

### Signing and notarization (macOS)

A release is Gatekeeper-clean when signing credentials are in the **environment**, and is
the unsigned bundle above when they are not. Both paths are the same command:

```bash
scripts/bundle-macos.sh            # the release build
scripts/bundle-macos.sh --check    # report which path it would take, and build nothing
```

The script only decides and reports — the signing is `tauri build`'s, and the variables
are the ones its bundler already reads. It exists so that a half-configured release fails
in a second rather than after a ten-minute build, and so the log says which bundle came
out. It also runs the build **from the repo root** (the CLI finds `src-tauri/` by walking
up from the working directory), so there is one command that cannot be run from the wrong
place.

| Variable | Path | What it is |
|----------|------|------------|
| `APPLE_SIGNING_IDENTITY` | signing | The identity, e.g. `Developer ID Application: Name (TEAMID)` |
| `APPLE_CERTIFICATE` · `APPLE_CERTIFICATE_PASSWORD` | signing, CI only | base64 `.p12` + its password; the CLI imports it into a temporary keychain, which a CI runner has no login keychain for |
| `APPLE_ID` · `APPLE_PASSWORD` · `APPLE_TEAM_ID` | notarization | Apple ID with an **app-specific** password |
| `APPLE_API_KEY` · `APPLE_API_ISSUER` · `APPLE_API_KEY_PATH` | notarization | App Store Connect key, instead of the row above |

Three outcomes, and what the user of the `.dmg` sees:

| Environment | `plan` | First launch on another Mac |
|-------------|--------|------------------------------|
| No `APPLE_SIGNING_IDENTITY` | `unsigned` | Gatekeeper refuses a double-click; **right-click → Open**, then *Open* in the dialog. This is today's build, and it still works. |
| Identity only | `signed` | Still blocked once *downloaded* — since macOS 10.15 a signed app also has to be notarized. The script says so and names the variables that finish the job. |
| Identity + either notarization set | `signed+notarized` | Opens on a double-click, with no warning. |

Anything half-configured — a certificate without its password, notarization credentials
without an identity, two of the three variables in a set, an `APPLE_API_KEY_PATH` that
points at nothing — exits **2** and names what is missing, before any build starts.

No credential is in this repo, and none can be: `src-tauri/tauri.conf.json` sets
`bundle.macOS.hardenedRuntime` (which notarization requires) and deliberately no
`signingIdentity`, so the identity has nowhere to live but the environment. In CI the
variables come from repository secrets of the same names; an unset secret arrives as an
empty variable, which is exactly the unsigned path — so a fork still gets a bundle rather
than a failed job. Values are never echoed, only variable names.

### The tutorial runtime in the bundle

The site is what a **learner** runs a tutorial in, and it needs no Python at all — that is
the whole first-run cost it deletes (README's step count: 7 steps and 2 terminals before,
2 steps and 0 terminals now). It is 72 MB of static files, so it rides the same way the
embedded interpreter does:

| | |
|---|---|
| staged by | `scripts/build-jupyterlite.sh` → `src-tauri/resources/jupyterlite` (untracked) |
| copied in by | `src-tauri/tauri.lite.conf.json`, an **overlay** — a `bundle.resources` entry naming a missing directory fails the build, so the main config must not name build output |
| added by | `make bundle` / `make bundle-app`, and `scripts/bundle-macos.sh` when the site is staged (`bundle: lite 101/245 tutorials runnable in the browser …`) |
| served by | `src-tauri/src/lite.rs`, read-only, on its own loopback port |
| found via | `$PRAXIS_LITE_SITE`, then `<resources>/jupyterlite`, then a checkout's `src-tauri/resources/jupyterlite` |

A bundle built without it opens a window whose *run* tab reports that this build carries
no site, and everything else behaves as it did. A bundle built **with** it and no Python
core is the interesting case, and it is the one the adoption is for: the library, the
reader and the kernel all work, and the checks/progression/construction the Python core
owns are named as unavailable rather than silently absent
([JupyterLite](jupyterlite.md#in-the-app-who-serves-it-and-what-happens-without-python)).

Two overlays compose — `tauri build --config src-tauri/tauri.lite.conf.json --config
src-tauri/tauri.embedded.conf.json` — because Tauri merges configs in the order given and
each names a different `bundle.resources` key; `scripts/bundle-macos.sh` adds whichever
payloads are staged.

### The Python runtime in the bundle

The shell does not reimplement the core — it starts `launcher/app.py` with a Python
interpreter (`src-tauri/src/library.rs`). Where both come from is decided at runtime, and
a release build can **carry** them so the `.app` needs nothing beside it.

**Discovery order**, the same in every build — an embedded runtime only ever adds the
first step:

| | The core (`curriculum.py` + `launcher/app.py` + `notebooks/`) | The interpreter |
|-|-|-|
| 1 | `<resources>/praxis-runtime/core` — this build's embedded copy | `<resources>/praxis-runtime/python/bin/python3` |
| 2 | `PRAXIS_ROOT` | `PRAXIS_PYTHON` |
| 3 | the first such directory above the binary, then above the cwd | `<root>/.venv/bin/python` |
| 4 | — | `python3` on `PATH` |

The embedded interpreter goes first because it is the only one *known* to carry the launch
extra; a shipped app that quietly borrowed the user's `python3` is the failure the order
prevents. Both halves must be present or neither is used, so a half-copied payload falls
back rather than running a bundle's core on a checkout's interpreter. **`PRAXIS_NO_EMBED=1`
ignores the embedded runtime** and takes the rest of the order — the escape hatch when a
shipped runtime is broken.

Row 1 needs the bundle's resource directory, and Tauri will not always name it: its
`resource_dir()` refuses any binary reached through a **symlinked** path (a relaunch-hijack
guard in tauri-utils), which an `.app` under a symlinked directory is — `/tmp`, a link to
`/private/tmp`, is the easy one to hit. The shell falls back to the bundle's own layout in
that case (`Contents/MacOS/…` beside `Contents/Resources`, `library::bundle_resources`), so
a moved bundle keeps the runtime it shipped instead of silently dropping to row 2 and
looking for a checkout it has no reason to have.

Nothing about a dev build changes: `cargo run` / `npm run dev` ship no resources, so they
read the table from row 2 exactly as they always did.

#### Building with the embed

```bash
scripts/embed-python.sh                    # stage the runtime (~300 MB, downloads CPython)
scripts/bundle-macos.sh --bundles app      # picks the payload up automatically
```

`scripts/embed-python.sh` writes `src-tauri/resources/praxis-runtime/`:

| | What |
|-|-|
| `python/` | a relocatable CPython 3.12 (python-build-standalone, fetched by uv) with `.[launch]` installed into it — non-editable, so `site-packages` holds real files rather than a path back into the checkout |
| `core/` | `curriculum.py` · `nbstatus.py` · `scaffold_notebooks.py` · `launcher/` · `praxis/` · `notebooks/` — the seed library included |

It proves the payload before staging it (`import fastapi, uvicorn, jinja2` and
`import curriculum, nbstatus, launcher.app` from the copy), and leaves nothing behind if
that fails — exit **2** means "cannot embed here", not "the build failed".
`--check` reports the plan; `--clean` removes the payload; `--python X.Y` picks the version.

The payload is **untracked** (`.gitignore`) and the copy into the bundle lives in an
**overlay** config, `src-tauri/tauri.embedded.conf.json`, rather than in `tauri.conf.json`:
a `bundle.resources` entry naming a missing directory fails the build, so putting it in the
main config would break every build that hasn't staged 300 MB first. Build by hand with:

```bash
npm --prefix ui exec -- tauri build --config src-tauri/tauri.embedded.conf.json
```

`scripts/bundle-macos.sh` adds that flag itself when the payload is there and says which
bundle it is making — `embed embedded` or `embed none` — because the two produce
identically-named artifacts that behave very differently once moved.

#### Building without it

Just don't stage the payload (or `scripts/embed-python.sh --clean` an old one). The bundle
is then the shell alone and needs a checkout with the launch extra beside it:

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[launch]'
```

Without one the window opens and the library view reports the missing piece (that is what
`LauncherStatus::failed` is for) rather than failing silently.

#### What an embedded bundle actually does

Verified on macOS 26.5 (arm64) with the `.app` copied to `/tmp`, no checkout anywhere above
it, `PRAXIS_ROOT`/`PRAXIS_PYTHON` unset and the working directory outside the repo: the
shell resolves `<app>/Contents/Resources/praxis-runtime`, starts uvicorn on the embedded
CPython, reaches `LauncherStatus` **ready**, and serves the whole loop — define a subject,
scaffold it, construct it to the rubric, and gate it behind the knowledge checks. The
launcher's own status line reads `embedded runtime: …/Contents/Resources/praxis-runtime/python/bin/python3`.

## Web build (optional target)

The same frontend runs in a plain browser — `ui/src/tauri.ts` falls back whenever
`__TAURI_INTERNALS__` is absent, so there is no Tauri-only code path to strip. Two pieces:

```bash
# 1. the API + notebook renderer
praxis-launch                       # http://127.0.0.1:8000 (PRAXIS_HOST / PRAXIS_PORT)

# 2. the frontend
npm --prefix ui run build           # -> ui/dist
npm --prefix ui run preview         # or any static server
```

The frontend looks for the launcher at `http://127.0.0.1:8000`; point it elsewhere at
build time with `VITE_PRAXIS_LAUNCHER=https://…`. Serve `ui/dist` from `localhost` or
`127.0.0.1` (any port) — cross-origin access is gated by `SHELL_ORIGIN_RE` in
`launcher/app.py`, which admits exactly those plus the Tauri origins. **Extend that regex
for a different host; never widen it to `*`.**

Two things the browser cannot do, by design: the native folder picker (the storage
settings view keeps a text field for exactly this reason) and *Open in Lab* on a machine
that isn't running the lab. Everything else — library, define a subject, construction,
knowledge checks, progress — is the launcher, and works.

`launcher/app.py` also serves its **own** HTML at `/`, which needs no build step at all;
that is the fastest way to browse a library over SSH.

## CI

`.github/workflows/ci.yml` mirrors `.chief/verify.sh` check for check, each scoped to what
the PR touched. The list of checks lives in the README's [gate
section](../../README.md#the-gate) and is not restated here.

Two things about it are packaging's, and are the reason this page mentions it at all:

- **`scripts/` and the three version manifests scope into the python job**, because that
  is where packaging is asserted (`tests/test_packaging.py`) — a lone version bump in
  `src-tauri/tauri.conf.json` must still reach a gate.
- **The Rust job builds the frontend first.** `src-tauri` embeds `ui/dist` at compile
  time and `build.rs` writes a placeholder when it is missing, so a green `cargo build`
  over an unbuilt frontend proves nothing.

CI installs `.[launch,dev]` so the launcher API tests run rather than skipping
themselves.

> **[CORRECTED 2026-09-03 — this section listed the gate as "the frontend build, the Rust
> build, and `pytest tests/`". That was three of the six checks CI actually runs; it had
> been out of date since `validate_nbgrader.py` and `praxis.gatefloor` were added, and the
> two documentation gates landed on 2026-09-03. The list now has one home and this page
> points at it rather than keeping a third copy.]**
