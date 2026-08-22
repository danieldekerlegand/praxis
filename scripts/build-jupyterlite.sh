#!/usr/bin/env bash
# scripts/build-jupyterlite.sh — the JupyterLite site a learner runs tutorials in.
#
# JupyterLite is a full JupyterLab on a Pyodide kernel, served as static files: the
# browser is the runtime, so nothing here has to be installed on the learner's machine.
# The site this writes is therefore build output, not a dependency — it lands under
# src-tauri/resources/ beside the embedded Python runtime (gitignored, staged, copied
# into a bundle) rather than in the tree.
#
# What is pinned lives in ONE place, praxis/lite.py, and is read back out through
# `python3 -m praxis.lite pins` — so this script cannot drift from what the tests assert
# was adopted. Its own Python lives in an isolated .lite-venv: jupyterlite-core is a
# BUILD dependency of the site, never of the product, and putting it in the repo's .venv
# would make the launch extra carry it forever.
#
# The contents tree is staged by `python3 -m praxis.lite stage`, which is where the
# safety argument is: every graded region is stripped, no answer key is copied, and a
# tutorial whose imports Pyodide cannot resolve is reported unavailable-in-browser
# rather than served and left to fail at its first import.
#
# Usage:
#   scripts/build-jupyterlite.sh [--check] [--force]
#     --check   report the plan and build nothing
#     --force   rebuild even when a site for these pins is already staged
#
# Env:
#   PRAXIS_LITE_SITE   where to write the site (default src-tauri/resources/jupyterlite)
#   PY                 the interpreter that reads praxis/lite.py (default .venv, else python3)
#
# Exit 2 means "misconfigured" — a missing toolchain, before anything is downloaded.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

check_only=0
force=0
for arg in "$@"; do
  case "$arg" in
    --check) check_only=1 ;;
    --force) force=1 ;;
    *) echo "lite: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# The same interpreter rule the Makefile and src-tauri/src/library.rs use.
PY="${PY:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}"
SITE="${PRAXIS_LITE_SITE:-$ROOT/src-tauri/resources/jupyterlite}"
WORK="$ROOT/src-tauri/resources/.jupyterlite-build"
LITE_VENV="$ROOT/.lite-venv"

"$PY" -m praxis.lite plan
echo "lite: plan site=$SITE"
echo "lite: plan builder=$LITE_VENV"

pins=()
while IFS= read -r line; do [ -n "$line" ] && pins+=("$line"); done < <("$PY" -m praxis.lite pins)

if [ "$check_only" -eq 1 ]; then
  echo "lite: plan check-only — nothing built"
  exit 0
fi

# Already staged for these pins? A site is 60+ MB of JupyterLab assets; `make build`
# runs this every time, so re-staging an unchanged one is the common case.
stamp="$SITE/praxis-lite.json"
if [ "$force" -eq 0 ] && [ -f "$stamp" ] \
   && "$PY" - "$stamp" <<'PYEOF'
import json, sys
from praxis import lite
try:
    manifest = json.loads(open(sys.argv[1]).read())
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if (
    manifest.get("jupyterlite") == lite.JUPYTERLITE_CORE
    and manifest.get("pyodideKernel") == lite.JUPYTERLITE_PYODIDE_KERNEL
) else 1)
PYEOF
then
  echo "lite: site already built for these pins — $SITE (--force to rebuild)"
  exit 0
fi

if command -v uv >/dev/null 2>&1; then
  [ -d "$LITE_VENV" ] || uv venv --python 3.12 "$LITE_VENV"
  uv pip install --quiet --python "$LITE_VENV/bin/python" "${pins[@]}"
else
  command -v python3 >/dev/null 2>&1 || { echo "lite: python3 is required" >&2; exit 2; }
  [ -d "$LITE_VENV" ] || python3 -m venv "$LITE_VENV"
  "$LITE_VENV/bin/python" -m pip install --quiet --upgrade pip
  "$LITE_VENV/bin/python" -m pip install --quiet "${pins[@]}"
fi

rm -rf "$WORK"
mkdir -p "$WORK"
"$PY" -m praxis.lite stage "$WORK/contents" --manifest "$WORK/praxis-lite.json"

# `jupyter lite build` is JupyterLite's own build; nothing here reimplements it.
rm -rf "$SITE"
( cd "$WORK" && "$LITE_VENV/bin/jupyter" lite build --contents contents --output-dir "$SITE" )

# The manifest travels with the site: it is what the shell reads to say which tutorials
# run in the browser and which are honestly unavailable there.
cp "$WORK/praxis-lite.json" "$SITE/praxis-lite.json"
rm -rf "$WORK"

echo "lite: built $SITE"
