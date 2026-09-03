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

# --- documentation structure gate --------------------------------------------
# The shape of docs/: every file linked from docs/README.md (docs/archive/ exempt), every
# file banner-stamped, no directory outside the standard's seven that isn't declared in
# docs/.structure-exceptions, and no markdown at the repo root but the Tier-1 five.
# A WALL, not a ratchet, unlike the link gate above — the tree was brought fully compliant
# on 2026-09-03 (16/16 banners, all 14 live subdocs linked plus 1 archived document which is
# exempt, 0 undeclared directories, 0 non-Tier-1 markdown at the repo root), so there is no
# pre-existing rot to retire and the cheapest moment to reject a violation is the one that
# introduces it. See scripts/check-docs-structure.mjs's header for the rules it restates.
if [ "${CHIEF_VERIFY_DOCLINKS:-1}" = 1 ] \
   && echo "$changed" | grep -qE '\.md$|^docs/' \
   && [ -f scripts/check-docs-structure.mjs ] && command -v node >/dev/null 2>&1; then
  node scripts/check-docs-structure.mjs \
    || { echo "verify: docs structure violation (see above)"; exit 1; }
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
# on), so a lone version bump in tauri.conf.json must reach this gate. The Makefile and
# README.md joined them for the same reason: test_packaging.py now pins what `make bundle`
# ships and what the README's first run asks a learner to do (docs/reference/jupyterlite.md).
# docs/reference/gate-authority.md is in scope for the same reason: tests/test_gate_authority.py
# reads it, so a claim edited out of the contract must fail the gate rather than pass unnoticed.
#
# nbgrader belongs in that toolchain probe, not just pytest/nbformat: it is a pinned CORE
# dependency (pyproject.toml) and `nbgrader validate` is the authoritative gate for graded
# cells, so an environment without it does not skip the gate — it fails every graded-cell
# test with "nbgrader validate is unavailable". A .venv predating the pin is exactly that
# environment, so repair it in place with the same editable install CI runs before giving
# up. `praxis.checks` resolves nbgrader's console script beside the running interpreter,
# so the interpreter that runs the tests must be the one that has it.
if echo "$changed" | grep -qE '\.(py|ipynb)$|^notebooks/|^tests/|^scripts/|^pyproject\.toml$|^ui/package\.json$|^src-tauri/tauri\.conf\.json$|^Makefile$|^README\.md$|^docs/reference/gate-authority\.md$'; then
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
    # The coverage ratchet. Gate coverage IS the product claim, and it sat at 24/245 for a
    # fortnight after the machinery to raise it had merged, because no check ever looked.
    # This one is cheap and offline (a fold over the notebooks and their answer keys, no
    # model, no launch extra) and it fails in one direction only: a domain, or the library,
    # gating fewer notebooks than notebooks/coverage-floor.json already recorded. A rise
    # never fails it. It also holds the README's stated figure to the recorded one, so the
    # number a reader meets cannot drift from the number the gate enforces.
    run "$py" -m praxis.gatefloor
    run "$py" -m pytest -q tests/
  else
    echo "skip: pytest/nbformat/nbgrader not installed (create .venv: uv venv .venv && uv pip install --python .venv/bin/python -e '.[launch,dev]')"
  fi
fi

[ "$fail" -eq 0 ] && echo "verify: PASS" || echo "verify: FAIL"
exit $fail
