# Packaging Praxis

> **Status:** Current · **Updated:** 2026-08-14 · **Owner:** praxis

Two distributable shapes come out of this repo, and both wrap the same Python core:

| Target | What it is | Built with |
|--------|------------|------------|
| **Desktop bundle** | A native app (`.app`/`.dmg`, `.msi`/`.exe`, `.deb`/`.AppImage`) around the Tauri shell | `tauri build` |
| **Web build** (optional) | `ui/dist` served by any static server, talking to a hand-started `praxis-launch` | `npm run build` + `praxis-launch` |

The shell is not the product — `launcher/app.py` and the notebook core are. Both targets
start from the same `ui/dist`, and both browse the same launcher API.

## Prerequisites

- **Rust** (stable, ≥ 1.77.2) and **Node 20+** with npm.
- **Python 3.10+** with the launch extra — the bundle *runs* the Python core, it does not
  contain it (see [The Python core is not inside the bundle](#the-python-core-is-not-inside-the-bundle)).
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
npm --prefix ui ci                      # once
npm --prefix ui exec -- tauri build     # release build + bundle
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
  for exactly this reason; the three checks stay three.
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

### The Python core is not inside the bundle

The shell discovers the core at runtime rather than embedding it
(`src-tauri/src/library.rs`), in this order:

1. `PRAXIS_ROOT` — a directory holding `curriculum.py`, `launcher/app.py` and `notebooks/`.
2. Otherwise the first such directory above the binary, then above the working directory.
   A `.app` sitting inside (or beside) a checkout therefore just works.

The interpreter is `PRAXIS_PYTHON`, else `<root>/.venv/bin/python`, else `python3` — and
it must have the launch extra:

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[launch]'
```

So a bundle shipped to another machine needs the checkout and that environment beside it;
without them the window opens and the library view reports the missing piece (that is
what `LauncherStatus::failed` is for) instead of failing silently. Embedding an
interpreter is not done here.

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

`.github/workflows/ci.yml` mirrors `.chief/verify.sh`: the frontend build, the Rust
build, and `pytest tests/`, each scoped to whether the PR touched `ui/`, `src-tauri/`, or
Python/notebooks — plus `scripts/` and the three version manifests, which scope into the
python job because that is where packaging is asserted. The Rust job builds the frontend first — `src-tauri` embeds `ui/dist`
at compile time, and `build.rs` writes a placeholder when it is missing, so a green cargo
build over an unbuilt frontend proves nothing.

CI installs `.[launch,dev]` so the launcher API tests run rather than skipping
themselves.
