#!/usr/bin/env bash
# .chief/verify.sh — Praxis merge gate. Path-scoped: run only the checks a branch's diff needs,
# and skip a check gracefully if its toolchain isn't installed (so early bootstrap branches pass).
set -uo pipefail

changed="$(git diff --name-only "$CHIEF_BASE_BRANCH"...HEAD)"
[ -z "$changed" ] && { echo "verify: no diff vs $CHIEF_BASE_BRANCH"; exit 0; }

# --- documentation link gate -------------------------------------------------
# Every local doc reference must resolve. RATCHET, not a wall: it compares this
# branch against the base and blocks only a REGRESSION, so pre-existing rot is
# retired deliberately instead of blocking every merge from day one. Local refs
# only — an external URL checker fails for network reasons, and a gate that fails
# for reasons unrelated to the change is a gate that gets switched off.
# Set CHIEF_VERIFY_DOCLINKS=0 to skip while iterating.
if [ "${CHIEF_VERIFY_DOCLINKS:-1}" = 1 ] \
   && echo "$changed" | grep -qE '\.md$|^docs/' \
   && [ -f scripts/check-doc-links.mjs ] && command -v node >/dev/null 2>&1; then
  node scripts/check-doc-links.mjs --ratchet --base "${CHIEF_BASE_BRANCH:-main}" \
    || { echo "verify: doc-link regression (see above)"; exit 1; }
fi


fail=0
run(){ echo "== $* =="; "$@" || { echo "FAIL: $*"; fail=1; }; }

# Frontend (TS/React). Runs BEFORE the Rust build: src-tauri embeds ui/dist at compile
# time, so building the frontend first means cargo checks the real bundle.
if echo "$changed" | grep -q '^ui/' && [ -f ui/package.json ]; then
  if command -v npm >/dev/null; then ( cd ui && npm ci --silent >/dev/null 2>&1; run npm run build ); else echo "skip: npm not installed"; fi
fi

# Tauri backend (Rust)
if echo "$changed" | grep -q '^src-tauri/' && [ -f src-tauri/Cargo.toml ]; then
  if command -v cargo >/dev/null; then ( cd src-tauri && run cargo build --quiet ); else echo "skip: cargo not installed"; fi
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
