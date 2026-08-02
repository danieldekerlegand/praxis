"""The launcher API the desktop shell browses through.

The shell (src-tauri/src/library.rs) starts launcher/app.py and reads /api/library, so
these are the contracts that break the in-app library if they drift: the JSON shape, the
badge map, the notebook render route, and the subject-definition endpoints the "define a
subject" view posts to.

No test here ever calls a model: `generate_and_save` is replaced wherever a subject is
defined, so the suite stays offline and spends nothing.

Skipped wholesale when the launch extra isn't installed — the core stays dependency-light
(pip install -e '.[launch]').
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi", reason="launch extra not installed")
pytest.importorskip("jinja2", reason="launch extra not installed")
from fastapi.testclient import TestClient  # noqa: E402

import launcher.app as launcher_app  # noqa: E402
from curriculum import CurriculumError, save_subject, subject_from_dict  # noqa: E402
from launcher.app import SHELL_ORIGIN_RE, _exit_with_parent, create_app  # noqa: E402
from praxis.llm import LLMConfigError, LLMError  # noqa: E402

CURRICULUM = {
    "title": "Sailing Navigation",
    "blurb": "Get a small boat somewhere on purpose.",
    "modules": [
        {
            "title": "Charts",
            "topics": [{"title": "Reading a Chart"}, {"title": "Dead Reckoning"}],
        }
    ],
}


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


# --- defining a subject ----------------------------------------------------


@pytest.fixture
def subjects_root(monkeypatch, tmp_path) -> Path:
    """Point the subject store at a temp dir — never the repo's own library."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "subjects"))
    return tmp_path / "subjects"


@pytest.fixture
def no_model(monkeypatch):
    """Replace the generator, so defining a subject in a test never calls a model."""

    def install(outcome):
        def fake(goal, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            subject = subject_from_dict(CURRICULUM, goal=goal, model="test-model")
            save_subject(subject)
            return subject

        monkeypatch.setattr(launcher_app, "generate_and_save", fake)

    return install


def test_defining_a_subject_persists_a_curriculum_for_review(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    no_model(None)
    res = client.post("/api/subjects", json={"goal": "I want to navigate a small boat"})

    assert res.status_code == 201
    body = res.json()
    assert body["slug"] == "sailing-navigation"
    assert body["goal"] == "I want to navigate a small boat"
    assert body["n_topics"] == 2
    assert body["modules"][0]["dir"] == "subjects/sailing-navigation/01-charts"

    stored = subjects_root / "sailing-navigation" / "curriculum.json"
    assert json.loads(stored.read_text())["title"] == "Sailing Navigation"
    assert client.get("/api/subjects").json()["subjects"][0]["slug"] == "sailing-navigation"
    assert client.get("/api/subjects/sailing-navigation").json() == body


def test_a_subject_with_no_goal_is_refused_before_any_call(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    no_model(AssertionError("must not reach the model"))
    assert client.post("/api/subjects", json={"goal": "   "}).status_code == 400
    assert client.post("/api/subjects", json={}).status_code == 400


@pytest.mark.parametrize(
    "error, status",
    [
        (LLMConfigError("no API key for provider 'anthropic'"), 503),
        (LLMError("anthropic call failed (429)"), 502),
        (CurriculumError("curriculum 'x' has no modules"), 422),
    ],
)
def test_each_failure_mode_is_reported_apart(
    client: TestClient, subjects_root: Path, no_model, error, status
) -> None:
    """The shell shows the launcher's message, so an unset key must not read as 500."""
    no_model(error)
    res = client.post("/api/subjects", json={"goal": "anything"})
    assert res.status_code == status
    assert str(error) in res.json()["error"]


def test_an_unknown_subject_is_a_404(client: TestClient, subjects_root: Path) -> None:
    assert client.get("/api/subjects").json() == {"subjects": []}
    assert client.get("/api/subjects/never-defined").status_code == 404


def test_a_subject_reaches_the_library_only_once_it_has_notebooks(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    """Defining a subject writes a curriculum, not notebooks — the badge counts hold."""
    before = client.get("/api/library").json()
    no_model(None)
    client.post("/api/subjects", json={"goal": "navigate a small boat"})
    assert client.get("/api/library").json()["total"] == before["total"]

    module = subjects_root / "sailing-navigation" / "01-charts"
    module.mkdir(parents=True)
    (module / "reading-a-chart.ipynb").write_text(
        json.dumps({"cells": [], "metadata": {"praxis": {"status": "scaffold"}},
                    "nbformat": 4, "nbformat_minor": 5})
    )

    after = client.get("/api/library").json()
    assert after["total"] == before["total"] + 1
    charts = next(d for d in after["domains"] if d["dir"].startswith("subjects/"))
    assert charts["name"] == "Charts"
    assert charts["topics"] == [{
        "title": "Reading a Chart",   # titled from the curriculum, not the filename
        "rel": "subjects/sailing-navigation/01-charts/reading-a-chart.ipynb",
        "status": "scaffold",
        "recommended": False,
        "note": "",
    }]
