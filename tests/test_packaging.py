"""Packaging: which bundle a release actually produces, and on whose credentials.

`scripts/bundle-macos.sh` is the release path. The thing worth asserting about it is not
that it can call `tauri build` — it is the *decision* it makes before doing so: signed
and notarized when the environment carries credentials, today's unsigned bundle when it
does not, and a refusal (before a ten-minute build) when the credentials are only half
there. `--check` reports that decision without building, so every case below is cheap.

The environment is passed explicitly, never inherited: a developer who really does have
`APPLE_SIGNING_IDENTITY` exported must not turn the unsigned case green.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bundle-macos.sh"

# A complete set of each of the two credential shapes tauri accepts.
APPLE_ID_CREDS = {"APPLE_ID": "release@example.com", "APPLE_PASSWORD": "abcd-efgh-ijkl-mnop", "APPLE_TEAM_ID": "TEAMID1234"}
IDENTITY = {"APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (TEAMID1234)"}


def check(**env: str) -> subprocess.CompletedProcess:
    """Run the release script's `--check`, with exactly the environment given."""
    return subprocess.run(
        ["bash", str(SCRIPT), "--check"],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
    )


def plan(result: subprocess.CompletedProcess) -> str:
    for line in result.stdout.splitlines():
        if line.startswith("bundle: plan "):
            return line.removeprefix("bundle: plan ")
    raise AssertionError(f"no plan reported:\n{result.stdout}\n{result.stderr}")


# --- the two paths ----------------------------------------------------------


def test_no_credentials_still_produces_a_bundle():
    """The fallback: an empty environment is not an error, it is today's unsigned build."""
    result = check()
    assert result.returncode == 0
    assert plan(result) == "unsigned"
    assert "right-click" in result.stdout


def test_an_identity_alone_signs_and_says_what_is_still_missing():
    result = check(**IDENTITY)
    assert result.returncode == 0
    assert plan(result) == "signed"
    # signed-but-unnotarized is still blocked once downloaded, so it must not read as done
    assert "APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID" in result.stdout


@pytest.mark.parametrize(
    "creds",
    [
        APPLE_ID_CREDS,
        {"APPLE_API_KEY": "KEYID", "APPLE_API_ISSUER": "issuer-uuid", "APPLE_API_KEY_PATH": str(SCRIPT)},
    ],
    ids=["apple-id", "api-key"],
)
def test_either_credential_set_notarizes(creds):
    result = check(**IDENTITY, **creds)
    assert result.returncode == 0
    assert plan(result) == "signed+notarized"


# --- the refusals -----------------------------------------------------------


def test_half_configured_notarization_fails_before_the_build():
    """Naming the missing variables is the whole point: tauri only says so after signing."""
    result = check(**IDENTITY, APPLE_ID=APPLE_ID_CREDS["APPLE_ID"])
    assert result.returncode == 2
    assert "APPLE_PASSWORD" in result.stderr and "APPLE_TEAM_ID" in result.stderr


def test_notarization_credentials_without_an_identity_fail():
    result = check(**APPLE_ID_CREDS)
    assert result.returncode == 2
    assert "APPLE_SIGNING_IDENTITY" in result.stderr


def test_a_certificate_without_its_password_fails():
    result = check(**IDENTITY, APPLE_CERTIFICATE="base64-p12")
    assert result.returncode == 2
    assert "APPLE_CERTIFICATE_PASSWORD" in result.stderr


def test_a_certificate_without_an_identity_fails():
    """Importing a certificate and then signing nothing with it is the silent failure."""
    result = check(APPLE_CERTIFICATE="base64-p12", APPLE_CERTIFICATE_PASSWORD="pw")
    assert result.returncode == 2
    assert "APPLE_SIGNING_IDENTITY" in result.stderr


def test_a_missing_api_key_file_fails():
    result = check(
        **IDENTITY,
        APPLE_API_KEY="KEYID",
        APPLE_API_ISSUER="issuer-uuid",
        APPLE_API_KEY_PATH=str(ROOT / "no-such-AuthKey.p8"),
    )
    assert result.returncode == 2
    assert "APPLE_API_KEY_PATH" in result.stderr


# --- credentials stay out of the repo, and out of the log -------------------


def test_a_secret_value_is_never_printed():
    """Build logs are public on a fork. Variable names may be logged; values may not."""
    result = check(**IDENTITY, **APPLE_ID_CREDS, APPLE_CERTIFICATE="p12-bytes", APPLE_CERTIFICATE_PASSWORD="s3cr3t")
    output = result.stdout + result.stderr
    for value in (*APPLE_ID_CREDS.values(), "p12-bytes", "s3cr3t", *IDENTITY.values()):
        assert value not in output


def test_no_signing_credential_is_committed():
    """The shell config pins hardened runtime — notarization needs it — and nothing else."""
    macos = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())["bundle"]["macOS"]
    assert macos["hardenedRuntime"] is True
    assert "signingIdentity" not in macos  # the identity comes from the environment, only


# --- where the build is started from ----------------------------------------


@pytest.mark.skipif(platform.system() != "Darwin", reason="the signing/notarizing path is macOS-only")
def test_the_build_runs_from_the_repo_root(tmp_path):
    """`tauri` finds src-tauri/ by walking up from the CWD, so a run from ui/ finds no app."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npm = fake_bin / "npm"
    npm.write_text('#!/usr/bin/env bash\necho "cwd=$PWD"\necho "args=$*"\n')
    npm.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SCRIPT)],  # no --check: this is the real invocation, with a fake npm
        cwd=tmp_path,  # started from somewhere else entirely
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"cwd={ROOT}" in result.stdout
    assert "args=--prefix ui exec -- tauri build" in result.stdout


# --- one version, three manifests -------------------------------------------
# Nothing derives one of these from another, so a release can name a .dmg 0.2.0 around a
# 0.1.0 core. scripts/check-versions.py is the single check; the release script runs it
# before building, and these tests are what put it in CI's python job.

VERSIONS = ROOT / "scripts" / "check-versions.py"
MANIFESTS = ("src-tauri/tauri.conf.json", "pyproject.toml", "ui/package.json")


def check_versions(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERSIONS), str(root)], capture_output=True, text=True)


def fake_manifests(root: Path, tauri: str, pyproject: str, ui: str) -> Path:
    """A repo-shaped tree declaring the three versions given, to test the failure paths."""
    (root / "src-tauri").mkdir()
    (root / "ui").mkdir()
    (root / "src-tauri" / "tauri.conf.json").write_text(json.dumps({"version": tauri} if tauri else {}))
    (root / "pyproject.toml").write_text(f'[project]\nname = "praxis"\nversion = "{pyproject}"\n')
    (root / "ui" / "package.json").write_text(json.dumps({"name": "praxis-ui", "version": ui}))
    return root


def test_the_three_manifests_declare_the_same_version():
    """Read here rather than through the checker, so the rule holds even if it doesn't."""
    tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())["version"]
    ui = json.loads((ROOT / "ui" / "package.json").read_text())["version"]
    pyproject = re.search(
        r"""^\[project\](?:.|\n)*?^version\s*=\s*["']([^"']+)["']""",
        (ROOT / "pyproject.toml").read_text(),
        re.MULTILINE,
    ).group(1)
    assert tauri == pyproject == ui, f"{MANIFESTS} disagree: {tauri} / {pyproject} / {ui}"


def test_the_check_passes_on_this_repo_and_reports_the_version():
    result = check_versions(ROOT)
    assert result.returncode == 0, result.stderr
    assert "in step" in result.stdout


def test_a_mismatch_names_every_manifest_and_the_version_it_declares(tmp_path):
    """The message is the fix: it must say which files disagree, and about what."""
    result = check_versions(fake_manifests(tmp_path, tauri="0.2.0", pyproject="0.1.0", ui="0.1.0"))
    assert result.returncode == 1
    for rel in MANIFESTS:
        assert rel in result.stderr
    assert "0.2.0" in result.stderr and "0.1.0" in result.stderr


def test_a_manifest_with_no_version_at_all_is_a_mismatch(tmp_path):
    result = check_versions(fake_manifests(tmp_path, tauri="", pyproject="0.1.0", ui="0.1.0"))
    assert result.returncode == 1
    assert "src-tauri/tauri.conf.json" in result.stderr


def test_a_release_reports_the_version_it_would_carry():
    """The release path runs the check itself, so a mismatch costs a second, not a build."""
    result = check()
    assert re.search(r"^bundle: version \S+ in step", result.stdout, re.MULTILINE), result.stdout
