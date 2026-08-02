# Packaging Praxis

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
runs exactly the command above and uploads the `.app` and `.dmg` as artifacts.

The app version comes from `version` in `tauri.conf.json`; keep it in step with
`pyproject.toml` and `ui/package.json` when cutting a release. Builds are **unsigned** —
macOS Gatekeeper will need a right-click → Open on first launch until a signing identity
is configured.

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
Python/notebooks. The Rust job builds the frontend first — `src-tauri` embeds `ui/dist`
at compile time, and `build.rs` writes a placeholder when it is missing, so a green cargo
build over an unbuilt frontend proves nothing.

CI installs `.[launch,dev]` so the launcher API tests run rather than skipping
themselves.
