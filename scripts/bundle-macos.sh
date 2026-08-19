#!/usr/bin/env bash
# scripts/bundle-macos.sh — the release bundle, signed and notarized when the environment
# says so, and today's unsigned bundle when it doesn't.
#
# Credentials live in the ENVIRONMENT (CI secrets, or a developer's own keychain) and
# never in this repo — nothing here reads a file of secrets, and nothing here prints a
# secret's VALUE, only whether the variable is set.
#
# The variable names are not ours: they are the ones `tauri build` itself looks for
# (tauri-bundler's macOS signing + notarization step). We read them only to decide which
# path a build is taking, to refuse a half-configured one before a 10-minute build, and
# to say so out loud — then we hand the same environment straight to the CLI.
#
#   signing        APPLE_SIGNING_IDENTITY          e.g. "Developer ID Application: … (TEAMID)"
#                  APPLE_CERTIFICATE               base64 .p12, CI only (no login keychain there)
#                  APPLE_CERTIFICATE_PASSWORD      its password
#   notarization   APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID          (app-specific password), or
#                  APPLE_API_KEY + APPLE_API_ISSUER + APPLE_API_KEY_PATH   (App Store Connect key)
#
# It also reports whether the bundle carries an embedded Python runtime — staged by
# scripts/embed-python.sh, opt-in, and the difference between a .app that runs anywhere
# and one that needs a checkout beside it (docs/reference/packaging.md).
#
# Usage:
#   scripts/bundle-macos.sh [--check] [extra tauri build args…]
#     --check   report the plan and exit without building
#
# Exit 2 means "misconfigured", not "build failed": the credentials are partly there, so
# the build would quietly produce something less than it looks like.
set -euo pipefail

# Run from the repo root. `tauri` locates src-tauri/ by walking up from the WORKING
# DIRECTORY, so a bundle started inside ui/ silently finds no app (CLAUDE.md, "Bundling").
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

check_only=0
tauri_args=()
for arg in "$@"; do
  case "$arg" in
    --check) check_only=1 ;;
    *) tauri_args+=("$arg") ;;
  esac
done

say() { echo "bundle: $*"; }
fail() { echo "bundle: $*" >&2; exit 2; }
have() { [ -n "${!1:-}" ]; }
# Names of the given variables that are NOT set — the message a misconfiguration needs.
missing() { local v out=(); for v in "$@"; do have "$v" || out+=("$v"); done; echo "${out[*]-}"; }

# --- the signing identity ----------------------------------------------------
signed=0
if have APPLE_SIGNING_IDENTITY; then
  signed=1
  if have APPLE_CERTIFICATE && ! have APPLE_CERTIFICATE_PASSWORD; then
    fail "APPLE_CERTIFICATE is set but APPLE_CERTIFICATE_PASSWORD is not — the certificate cannot be imported without it."
  fi
elif have APPLE_CERTIFICATE; then
  fail "APPLE_CERTIFICATE is set but APPLE_SIGNING_IDENTITY is not — the certificate would be imported and then nothing signed with it."
fi

# --- notarization credentials ------------------------------------------------
# Either complete set will do; a partial one is the failure worth catching, because
# tauri signs first and only then discovers it cannot notarize.
APPLE_ID_SET=(APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID)
API_KEY_SET=(APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH)
missing_id="$(missing "${APPLE_ID_SET[@]}")"
missing_key="$(missing "${API_KEY_SET[@]}")"

notarized=0
if [ -z "$missing_id" ] || [ -z "$missing_key" ]; then
  notarized=1
elif [ "$missing_id" != "${APPLE_ID_SET[*]}" ]; then
  fail "incomplete notarization credentials — missing: $missing_id"
elif [ "$missing_key" != "${API_KEY_SET[*]}" ]; then
  fail "incomplete notarization credentials — missing: $missing_key"
fi

if [ "$notarized" = 1 ]; then
  [ "$signed" = 1 ] || fail "notarization credentials are set but APPLE_SIGNING_IDENTITY is not — Apple only notarizes a signed app."
  if have APPLE_API_KEY_PATH && [ ! -f "$APPLE_API_KEY_PATH" ]; then
    fail "APPLE_API_KEY_PATH does not point at a file — the App Store Connect key (.p8) must exist before the build."
  fi
fi

# --- what this build will therefore be ---------------------------------------
if [ "$signed" = 1 ] && [ "$notarized" = 1 ]; then
  plan="signed+notarized"
  if [ -z "$missing_id" ]; then notary="APPLE_ID"; else notary="APPLE_API_KEY"; fi
  say "signing with APPLE_SIGNING_IDENTITY; notarizing with $notary."
  say "Gatekeeper opens the result on first double-click — no right-click → Open."
elif [ "$signed" = 1 ]; then
  plan="signed"
  say "signing with APPLE_SIGNING_IDENTITY; no notarization credentials in the environment."
  say "Gatekeeper still blocks a DOWNLOADED copy of a signed-but-unnotarized app: set ${APPLE_ID_SET[*]} (or ${API_KEY_SET[*]}) to finish the job."
else
  plan="unsigned"
  say "no APPLE_SIGNING_IDENTITY in the environment — building the unsigned bundle."
  say "macOS Gatekeeper will need a right-click → Open on first launch (docs/reference/packaging.md)."
fi
say "plan $plan"

# --- the version this release will carry --------------------------------------
# Three manifests declare it and nothing derives one from another, so a release can
# name a .dmg 0.2.0 around a 0.1.0 core. Refused here for the same reason as every
# check above: before the build, not after it. scripts/check-versions.py names the
# files that disagree; we only turn its exit into this script's "misconfigured" 2.
command -v python3 >/dev/null 2>&1 \
  || fail "python3 is needed to check the release version across the manifests (it is a prerequisite of the bundle anyway — docs/reference/packaging.md)."
version="$(python3 scripts/check-versions.py)" \
  || fail "the manifests above disagree — bump them together before cutting a release."
say "$version"

# --- the Python runtime this bundle will (or will not) carry -------------------
# Staged by scripts/embed-python.sh, untracked, and opt-in: with the payload there the
# overlay config copies it into the bundle's resources and src-tauri/src/library.rs runs
# it in preference to anything on the machine; without it, the bundle is the shell only
# and needs a checkout with the launch extra beside it. Reported either way, because the
# two produce identically-named artifacts that behave very differently once moved.
EMBED_STAGE="$ROOT/src-tauri/resources/praxis-runtime"
EMBED_CONFIG="src-tauri/tauri.embedded.conf.json"
if [ -d "$EMBED_STAGE/python" ] && [ -d "$EMBED_STAGE/core" ]; then
  embed="embedded"
  say "embed $embed — $EMBED_STAGE goes into the bundle ($EMBED_CONFIG)."
  tauri_args=(--config "$EMBED_CONFIG" ${tauri_args[@]+"${tauri_args[@]}"})
elif [ -e "$EMBED_STAGE" ]; then
  fail "$EMBED_STAGE exists but has no python/ + core/ — an interrupted scripts/embed-python.sh. Re-run it, or --clean it away."
else
  embed="none"
  say "embed $embed — the .app will need a checkout with the launch extra beside it; scripts/embed-python.sh stages one to ship instead."
fi

if [ "$check_only" = 1 ]; then
  say "--check: not building."
  exit 0
fi

# Only past here does the platform matter: the credentials above are read the same way
# anywhere (so `--check` is portable, and CI can assert on it from Linux), but signing
# and notarization are macOS tools.
if [ "$(uname -s)" != "Darwin" ]; then
  fail "this is the macOS release path; on $(uname -s) build with: npm --prefix ui exec -- tauri build"
fi

# `tauri build` runs beforeBuildCommand itself, so ui/dist is rebuilt here and no stale
# frontend can be embedded. The environment above is passed through untouched.
say "running: npm --prefix ui exec -- tauri build ${tauri_args[*]-}"
exec npm --prefix ui exec -- tauri build ${tauri_args[@]+"${tauri_args[@]}"}
