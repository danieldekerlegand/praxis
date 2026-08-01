#!/usr/bin/env bash
# .chief/verify.sh — Praxis merge gate. Path-scoped: run only the checks a branch's diff needs,
# and skip a check gracefully if its toolchain isn't installed (so early bootstrap branches pass).
set -uo pipefail

changed="$(git diff --name-only "$CHIEF_BASE_BRANCH"...HEAD)"
[ -z "$changed" ] && { echo "verify: no diff vs $CHIEF_BASE_BRANCH"; exit 0; }

fail=0
run(){ echo "== $* =="; "$@" || { echo "FAIL: $*"; fail=1; }; }

# Tauri backend (Rust)
if echo "$changed" | grep -q '^src-tauri/' && [ -f src-tauri/Cargo.toml ]; then
  if command -v cargo >/dev/null; then ( cd src-tauri && run cargo build --quiet ); else echo "skip: cargo not installed"; fi
fi

# Frontend (TS/React)
if echo "$changed" | grep -q '^ui/' && [ -f ui/package.json ]; then
  if command -v npm >/dev/null; then ( cd ui && npm ci --silent >/dev/null 2>&1; run npm run build ); else echo "skip: npm not installed"; fi
fi

# Notebook-construction core + the completion gate (the reusable Python core).
# Prefer a repo-local .venv — the system python3 usually lacks pytest/nbformat, and a
# silently-skipped gate is worse than no gate.
if echo "$changed" | grep -qE '\.(py|ipynb)$|^notebooks/|^tests/'; then
  py=python3
  [ -x .venv/bin/python ] && py=.venv/bin/python
  if "$py" -c 'import pytest, nbformat' >/dev/null 2>&1; then
    run "$py" -m pytest -q tests/
  else
    echo "skip: pytest/nbformat not installed (create .venv: uv venv .venv && uv pip install --python .venv/bin/python pytest nbformat)"
  fi
fi

[ "$fail" -eq 0 ] && echo "verify: PASS" || echo "verify: FAIL"
exit $fail
