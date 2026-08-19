#!/usr/bin/env bash
# scripts/embed-python.sh — build the Python runtime a standalone bundle carries.
#
# Without this, a shipped Praxis is the shell only: src-tauri/src/library.rs finds the
# core by walking up from the binary and an interpreter via PRAXIS_PYTHON / .venv /
# python3, so a .app moved away from a checkout-with-the-launch-extra opens a window that
# can only explain itself (LauncherStatus::failed). This stages the missing half:
#
#   src-tauri/resources/praxis-runtime/
#     python/   a relocatable CPython (python-build-standalone, via uv) with the launch extra
#     core/     curriculum.py · nbstatus.py · scaffold_notebooks.py · launcher/ · praxis/ · notebooks/
#
# src-tauri/tauri.embedded.conf.json copies that directory into the bundle's resources,
# and library.rs prefers it over every other interpreter — see docs/reference/packaging.md.
#
# Nothing here is required to build Praxis: the payload is untracked, the overlay config
# is opt-in, and a build without it discovers a checkout exactly as it always has.
#
# Usage:
#   scripts/embed-python.sh [--check] [--clean] [--python X.Y]
#     --check   report the plan and exit without downloading or copying anything
#     --clean   delete the staged runtime and exit
#
# Exit 2 means "cannot embed here" (no uv, an unusable payload) — not "the build failed".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The one path this and the shell agree on: `RUNTIME_DIR` in src-tauri/src/library.rs is
# the leaf name, and tauri.embedded.conf.json copies this directory in under it.
STAGE="$ROOT/src-tauri/resources/praxis-runtime"
CONFIG="src-tauri/tauri.embedded.conf.json"

# 3.12 rather than the newest: it is what the launch extra (jupyterlab, nbconvert) has
# wheels for everywhere, and an embedded runtime that has to compile anything is not one.
PY_VERSION="${PRAXIS_EMBED_PYTHON:-3.12}"

# What a checkout is, from library.rs's `is_root` (curriculum.py + launcher/app.py +
# notebooks/) plus the modules those import. Copied whole; the seed library is the product.
CORE=(curriculum.py nbstatus.py scaffold_notebooks.py launcher praxis notebooks)

check_only=0
clean=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check_only=1 ;;
    --clean) clean=1 ;;
    --python) shift; PY_VERSION="${1:?--python needs a version, e.g. 3.12}" ;;
    *) echo "embed: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

say() { echo "embed: $*"; }
fail() { echo "embed: $*" >&2; exit 2; }

if [ "$clean" = 1 ]; then
  rm -rf "$STAGE"
  say "removed $STAGE — the next bundle is the unembedded one."
  exit 0
fi

# --- what this would produce --------------------------------------------------
say "target $STAGE"
say "python $PY_VERSION (python-build-standalone, downloaded by uv) + the launch extra"
say "core ${CORE[*]}"
say "bundle with: npm --prefix ui exec -- tauri build --config $CONFIG"
say "plan embed"

if [ "$check_only" = 1 ]; then
  say "--check: not building."
  exit 0
fi

command -v uv >/dev/null 2>&1 \
  || fail "uv is needed to fetch a relocatable interpreter (https://docs.astral.sh/uv/) — install it, or set PRAXIS_PYTHON and ship the unembedded bundle."

# --- the interpreter ----------------------------------------------------------
# uv installs into a versioned directory of its own naming, so install into a scratch dir
# and take whatever single tree lands there. -L dereferences: the copy that ends up in a
# .app must not depend on symlinks the bundler walks past.
rm -rf "$STAGE"
mkdir -p "$STAGE"
scratch="$(mktemp -d)"
staged=0
# Anything short of the verified end is not a runtime. Cleaning up here means a failed
# embed leaves no payload for scripts/bundle-macos.sh to refuse — the error the user has
# to act on is the one above, not one from the next command they run.
# Installing this project into the embedded interpreter has setuptools build it, which
# drops a build/ in the checkout. Ours to clean up — unless one was already there.
[ -e "$ROOT/build" ] && build_was_there=1 || build_was_there=0
cleanup() {
  rm -rf "$scratch"
  [ "$staged" = 1 ] || rm -rf "$STAGE"
  [ "$build_was_there" = 1 ] || rm -rf "$ROOT/build"
}
trap cleanup EXIT

say "downloading CPython ${PY_VERSION}…"
UV_PYTHON_INSTALL_DIR="$scratch" uv python install --install-dir "$scratch" --no-bin "$PY_VERSION" >&2 \
  || fail "uv could not install CPython $PY_VERSION."
installed="$(find "$scratch" -maxdepth 1 -mindepth 1 -type d | head -1)"
[ -n "$installed" ] || fail "uv installed CPython $PY_VERSION but left nothing in $scratch."
cp -RL "$installed" "$STAGE/python"

# uv stamps its managed installs EXTERNALLY-MANAGED so a user cannot mutate the copy
# shared by every project on the machine. This is not that copy: it is ours, private to
# this bundle, and filling it is the entire point — so the marker comes off it.
find "$STAGE/python" -name 'EXTERNALLY-MANAGED' -delete

python="$STAGE/python/bin/python3"
[ -x "$python" ] || python="$STAGE/python/python.exe"
[ -x "$python" ] || fail "no interpreter under $STAGE/python — uv's layout changed; library.rs looks for bin/python3 or python.exe."

# --- the launch extra, into that interpreter ----------------------------------
# Installed non-editably so site-packages holds real files rather than a path back into
# this checkout. Console scripts get an absolute shebang and are NOT used: the shell runs
# `python -m uvicorn`, which survives the move.
say "installing the launch extra…"
uv pip install --python "$python" --no-cache "$ROOT[launch]" >&2 \
  || fail "could not install the launch extra into the embedded interpreter."

# --- the core -----------------------------------------------------------------
mkdir -p "$STAGE/core"
for item in "${CORE[@]}"; do
  [ -e "$ROOT/$item" ] || fail "$item is missing from this checkout — nothing to embed."
  cp -R "$ROOT/$item" "$STAGE/core/"
done
find "$STAGE/core" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/core" -name '.ipynb_checkpoints' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# --- prove it, rather than claim it -------------------------------------------
# The whole point of embedding is that the shipped app needs nothing beside it, so the
# imports the launcher makes are run here, from the copy, before anyone bundles it.
"$python" -c 'import fastapi, uvicorn, jinja2' \
  || fail "the embedded interpreter cannot import fastapi/uvicorn/jinja2 — it would fail the shell's preflight."
PYTHONPATH="$STAGE/core" "$python" -c 'import curriculum, nbstatus, launcher.app' \
  || fail "the embedded core does not import — the copy under $STAGE/core is incomplete."

staged=1
say "$(du -sh "$STAGE" | cut -f1) staged: $("$python" -c 'import sys; print(sys.version.split()[0])') + $(ls "$STAGE/core" | wc -l | tr -d ' ') core entries"
say "done — bundle it with: npm --prefix ui exec -- tauri build --config $CONFIG"
