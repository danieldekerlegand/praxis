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
# The three manifests and scripts/ are in scope too: tests/test_packaging.py is where the
# release version is pinned in step across them (and where the release script is asserted
# on), so a lone version bump in tauri.conf.json must reach this gate.
#
# nbgrader belongs in that toolchain probe, not just pytest/nbformat: it is a pinned CORE
# dependency (pyproject.toml) and `nbgrader validate` is the authoritative gate for graded
# cells, so an environment without it does not skip the gate — it fails every graded-cell
# test with "nbgrader validate is unavailable". A .venv predating the pin is exactly that
# environment, so repair it in place with the same editable install CI runs before giving
# up. `praxis.checks` resolves nbgrader's console script beside the running interpreter,
# so the interpreter that runs the tests must be the one that has it.
if echo "$changed" | grep -qE '\.(py|ipynb)$|^notebooks/|^tests/|^scripts/|^pyproject\.toml$|^ui/package\.json$|^src-tauri/tauri\.conf\.json$'; then
  ready(){ [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
           "$1" -c 'import pytest, nbformat, nbgrader' >/dev/null 2>&1; }
  bootstrap(){ echo "verify: installing the pinned python deps into $1"
               if command -v uv >/dev/null 2>&1; then
                 uv pip install --quiet --python "$1" -e . >/dev/null 2>&1
               else
                 "$1" -m pip install --quiet -e . >/dev/null 2>&1
               fi; }
  py=""
  preferred=python3
  [ -x .venv/bin/python ] && preferred=.venv/bin/python
  if ready "$preferred"; then py="$preferred"
  elif bootstrap "$preferred" && ready "$preferred"; then py="$preferred"
  elif [ "$preferred" != python3 ] && ready python3; then py=python3
  fi
  if [ -n "$py" ]; then
    run "$py" scripts/validate_nbgrader.py notebooks
    run "$py" -m pytest -q tests/
  else
    echo "skip: pytest/nbformat/nbgrader not installed (create .venv: uv venv .venv && uv pip install --python .venv/bin/python -e '.[launch,dev]')"
  fi
fi

[ "$fail" -eq 0 ] && echo "verify: PASS" || echo "verify: FAIL"
exit $fail
