"""The launcher API the desktop shell browses through.

The shell (src-tauri/src/library.rs) starts launcher/app.py and reads /api/library, so
these are the contracts that break the in-app library if they drift: the JSON shape, the
badge map, and the notebook render route.

Skipped wholesale when the launch extra isn't installed — the core stays dependency-light
(pip install -e '.[launch]').
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi", reason="launch extra not installed")
pytest.importorskip("jinja2", reason="launch extra not installed")
from fastapi.testclient import TestClient  # noqa: E402

from launcher.app import SHELL_ORIGIN_RE, _exit_with_parent, create_app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def library(client: TestClient) -> dict:
    res = client.get("/api/library")
    assert res.status_code == 200
    return res.json()


def test_healthz_is_the_shells_readiness_probe(client: TestClient) -> None:
    """src-tauri polls this over a raw socket and matches the body exactly."""
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.text == "ok"


def test_library_carries_every_seed_notebook(library: dict) -> None:
    on_disk = len(list((ROOT / "notebooks").rglob("*.ipynb")))
    assert library["total"] == on_disk
    assert sum(d["n"] for d in library["domains"]) == on_disk
    assert len(library["domains"]) >= 10


def test_topics_have_what_the_shell_renders(library: dict) -> None:
    for domain in library["domains"]:
        assert {"dir", "name", "title", "blurb", "topics", "n", "done"} <= domain.keys()
        for topic in domain["topics"]:
            assert {"title", "rel", "status", "recommended", "note"} <= topic.keys()
            assert topic["status"] in library["badge"]
            assert (ROOT / "notebooks" / topic["rel"]).exists()


def test_badges_come_from_nbstatus(library: dict) -> None:
    from nbstatus import BADGE

    assert library["badge"] == BADGE
    assert sum(library["counts"].values()) == library["total"]


def test_render_serves_a_notebook_and_refuses_escapes(client: TestClient, library: dict) -> None:
    rel = library["domains"][0]["topics"][0]["rel"]
    assert client.get(f"/render/{rel}").status_code == 200
    assert client.get("/render/../pyproject.toml").status_code == 404


def test_parent_watchdog_runs_as_a_daemon() -> None:
    """Started with our own ppid, so it just waits — never assert the exit path here."""
    import os

    thread = _exit_with_parent(os.getppid(), interval=30.0)
    assert thread.daemon and thread.is_alive()


def test_only_a_local_shell_origin_is_allowed() -> None:
    import re

    pattern = re.compile(SHELL_ORIGIN_RE)
    assert pattern.match("tauri://localhost")
    assert pattern.match("http://localhost:1420")
    assert not pattern.match("https://example.com")
