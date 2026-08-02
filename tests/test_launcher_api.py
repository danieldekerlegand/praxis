"""The launcher API the desktop shell browses through.

The shell (src-tauri/src/library.rs) starts launcher/app.py and reads /api/library, so
these are the contracts that break the in-app library if they drift: the JSON shape, the
badge map, the notebook render route, and the subject-definition endpoints the "define a
subject" view posts to.

No test here ever calls a model: `generate_and_save` is replaced wherever a subject is
defined and `construct_topic` wherever one is constructed, so the suite stays offline
and spends nothing.

Skipped wholesale when the launch extra isn't installed — the core stays dependency-light
(pip install -e '.[launch]').
"""

from __future__ import annotations

import json
import sys
import threading
import time
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


def test_scaffolding_a_subject_puts_real_notebooks_in_the_library(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    """The end-to-end write path: goal -> curriculum -> 🔴 notebooks the shell can browse."""
    before = client.get("/api/library").json()
    no_model(None)
    client.post("/api/subjects", json={"goal": "navigate a small boat"})

    res = client.post("/api/subjects/sailing-navigation/scaffold")
    assert res.status_code == 200
    assert res.json() == {
        "slug": "sailing-navigation",
        "created": 2,
        "skipped": 0,
        "n_topics": 2,
        "dir": "subjects/sailing-navigation",
    }

    module = subjects_root / "sailing-navigation" / "01-charts"
    assert sorted(p.name for p in module.glob("*.ipynb")) == [
        "dead-reckoning.ipynb", "reading-a-chart.ipynb",
    ]

    after = client.get("/api/library").json()
    assert after["total"] == before["total"] + 2
    charts = next(d for d in after["domains"] if d["dir"].startswith("subjects/"))
    assert charts["n"] == 2 and charts["done"] == 0
    assert {t["status"] for t in charts["topics"]} == {"scaffold"}
    assert [t["title"] for t in charts["topics"]] == ["Dead Reckoning", "Reading a Chart"]


def test_rescaffolding_is_idempotent_and_an_unknown_subject_is_a_404(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    no_model(None)
    client.post("/api/subjects", json={"goal": "navigate a small boat"})
    client.post("/api/subjects/sailing-navigation/scaffold")

    again = client.post("/api/subjects/sailing-navigation/scaffold")
    assert again.json()["created"] == 0 and again.json()["skipped"] == 2
    assert client.post("/api/subjects/never-defined/scaffold").status_code == 404


def test_a_relocated_subject_is_still_renderable(
    client: TestClient, subjects_root: Path, no_model
) -> None:
    """`rel` is always `subjects/<slug>/...`; PRAXIS_SUBJECTS_DIR moves the file."""
    no_model(None)
    client.post("/api/subjects", json={"goal": "navigate a small boat"})
    client.post("/api/subjects/sailing-navigation/scaffold")

    rel = "subjects/sailing-navigation/01-charts/reading-a-chart.ipynb"
    assert launcher_app.library_path(rel) == subjects_root / "sailing-navigation" / (
        "01-charts/reading-a-chart.ipynb")
    assert client.get(f"/render/{rel}").status_code == 200
    assert launcher_app.library_path("subjects/../../pyproject.toml") is None


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


# --- constructing what was scaffolded ---------------------------------------
#
# These drive the real praxis/construct.py — only the provider is replaced. So the
# grader, the skip-if-✅ rule and the "never write a draft that fails" rule are the
# production ones, and what the endpoints report is what actually happened on disk.

PROSE = (
    "This section is written out in full, concrete and specific, the way a refresher "
    "for a colleague who already knows the neighbouring ideas actually reads. "
)

LINKS = (
    "\n\n- [The Python docs](https://docs.python.org/3/)\n"
    "- [Project Jupyter](https://jupyter.org/)\n"
    "- [nbformat](https://nbformat.readthedocs.io/en/latest/)\n"
)


def passing_reply() -> str:
    """A model reply that clears the grader, built from the rubric's own section list."""
    from praxis.rubric import RUBRIC_SECTIONS

    cells = [{"type": "markdown", "source": f"## {n}. {section}\n\n{PROSE * 10}"}
             for n, section in enumerate(RUBRIC_SECTIONS, 1)]
    cells[-1]["source"] += LINKS  # Resources, and it stays last: the grader reads to EOF
    code = [{"type": "code", "source": "print(sum([1, 2, 3]))"},
            {"type": "code", "source": "import math\nprint(round(math.pi, 3))"}]
    return json.dumps({"cells": cells[:-1] + code + cells[-1:]})


def thin_reply() -> str:
    """What a lazy model returns: nothing that could pass for a finished notebook."""
    return json.dumps({"cells": [{"type": "markdown", "source": "## 1. What & Why\n\nx"}]})


@pytest.fixture
def model(monkeypatch):
    """Replace the provider the launcher would call. Construction itself stays real.

    Filling a notebook and writing the knowledge checks that gate it are two calls with
    two system prompts; the returned list counts the notebook ones, so a test can still
    say "this spent nothing". What the checks pass produced is asserted off disk.
    """
    from praxis.checks import SYSTEM_PROMPT as CHECKS_SYSTEM_PROMPT
    from praxis.llm import LLMConfig
    from test_checks import good_checks
    from test_checks import reply as checks_reply

    def install(reply=passing_reply, block: threading.Event | None = None):
        calls: list[str] = []

        class Fake:
            def __init__(self):
                self.config = LLMConfig(provider="openai", model="test-model", api_key="k")

            def complete(self, prompt, **kwargs):
                if kwargs.get("system") == CHECKS_SYSTEM_PROMPT:
                    return checks_reply(
                        good_checks(runnable="NO `code` checks" not in prompt))
                calls.append(prompt)
                if block is not None:
                    block.wait(timeout=10)
                return reply()

        monkeypatch.setattr(launcher_app, "LLMClient", Fake)
        return calls

    return install


def await_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    """Poll the job the way the shell does, and hand back its final state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f"/api/construct/{job_id}")
        assert res.status_code == 200
        job = res.json()
        if job["state"] == "done":
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


@pytest.fixture
def scaffolded(client: TestClient, subjects_root: Path, no_model) -> str:
    """A defined + scaffolded subject: two 🔴 notebooks waiting to be constructed."""
    no_model(None)
    client.post("/api/subjects", json={"goal": "navigate a small boat"})
    client.post("/api/subjects/sailing-navigation/scaffold")
    return "sailing-navigation"


def test_constructing_a_subject_fills_every_notebook_in_the_library(
    client: TestClient, scaffolded: str, model
) -> None:
    """The headline flow: define -> scaffold -> construct, ending ✅ and browsable."""
    calls = model()

    res = client.post("/api/construct", json={"subject": scaffolded})
    assert res.status_code == 202
    started = res.json()
    assert started["kind"] == "subject" and started["n"] == 2
    assert [i["badge"] for i in started["items"]] == ["scaffold", "scaffold"]

    job = await_job(client, started["id"])
    assert (job["constructed"], job["skipped"], job["failed"]) == (2, 0, 0)
    assert {i["phase"] for i in job["items"]} == {"constructed"}
    assert {i["badge"] for i in job["items"]} == {"complete"}
    assert len(calls) == 2

    charts = next(d for d in client.get("/api/library").json()["domains"]
                  if d["dir"].startswith("subjects/"))
    assert charts["done"] == charts["n"] == 2
    for topic in charts["topics"]:
        assert topic["status"] == "complete"
        assert client.get(f"/render/{topic['rel']}").status_code == 200


def test_a_second_run_skips_what_is_already_complete(
    client: TestClient, scaffolded: str, model
) -> None:
    """Resumable and idempotent: re-running spends nothing and clobbers nothing."""
    model()
    first = await_job(client, client.post(
        "/api/construct", json={"subject": scaffolded}).json()["id"])
    written = {i["rel"]: (Path(launcher_app.library_path(i["rel"])).read_bytes())
               for i in first["items"]}

    calls = model()
    again = await_job(client, client.post(
        "/api/construct", json={"subject": scaffolded}).json()["id"])

    assert (again["constructed"], again["skipped"]) == (0, 2)
    assert calls == []
    for rel, before in written.items():
        assert Path(launcher_app.library_path(rel)).read_bytes() == before


def test_one_topic_can_be_constructed_on_its_own(
    client: TestClient, scaffolded: str, model
) -> None:
    calls = model()
    rel = "subjects/sailing-navigation/01-charts/dead-reckoning.ipynb"

    job = await_job(client, client.post("/api/construct", json={"rel": rel}).json()["id"])

    assert job["kind"] == "topic" and job["n"] == 1
    assert job["items"][0]["badge"] == "complete"
    assert len(calls) == 1
    library = client.get("/api/library").json()
    charts = next(d for d in library["domains"] if d["dir"].startswith("subjects/"))
    assert charts["done"] == 1  # only the one that was asked for


def test_a_constructed_topic_comes_back_gated(
    client: TestClient, scaffolded: str, model
) -> None:
    """A run reports the gate it wrote — counted off the file, the way the badge is."""
    from praxis.checks import GATED_SECTIONS, checks_path, checkset_failures, load_checks

    model()
    rel = "subjects/sailing-navigation/01-charts/dead-reckoning.ipynb"

    job = await_job(client, client.post("/api/construct", json={"rel": rel}).json()["id"])

    item = job["items"][0]
    assert item["checksPhase"] == "generated"
    assert item["checks"] >= len(GATED_SECTIONS)
    doc = load_checks(checks_path(launcher_app.library_path(rel)))
    assert checkset_failures(doc) == []
    assert item["checks"] == len(doc["checks"])


def test_a_module_can_be_constructed_by_directory(
    client: TestClient, scaffolded: str, model
) -> None:
    model()

    job = await_job(client, client.post(
        "/api/construct", json={"domain": "subjects/sailing-navigation/01-charts"}
    ).json()["id"])

    assert job["kind"] == "module" and job["constructed"] == 2


def test_a_draft_that_fails_the_gate_is_never_written(
    client: TestClient, scaffolded: str, model
) -> None:
    """The anti-fabrication contract, through the API: 🔴 stays 🔴, nothing goes ✅."""
    rel = "subjects/sailing-navigation/01-charts/dead-reckoning.ipynb"
    before = Path(launcher_app.library_path(rel)).read_bytes()
    model(reply=thin_reply)

    job = await_job(client, client.post("/api/construct", json={"rel": rel}).json()["id"])

    item = job["items"][0]
    assert (job["failed"], item["phase"], item["badge"]) == (1, "failed", "scaffold")
    assert item["failures"]  # the grader's own sentences, handed back to the UI
    # Nothing to gate, so nothing claims to gate it.
    assert (item["checks"], item["checksPhase"]) == (0, "")
    assert Path(launcher_app.library_path(rel)).read_bytes() == before
    library = client.get("/api/library").json()
    charts = next(d for d in library["domains"] if d["dir"].startswith("subjects/"))
    assert charts["done"] == 0


def test_nothing_is_started_without_a_configured_model(
    client: TestClient, scaffolded: str, monkeypatch
) -> None:
    def unconfigured():
        raise LLMConfigError("no API key for provider 'anthropic'")

    monkeypatch.setattr(launcher_app, "LLMClient", unconfigured)
    res = client.post("/api/construct", json={"subject": scaffolded})

    assert res.status_code == 503
    assert "no API key" in res.json()["error"]


def test_only_one_construction_runs_at_a_time(
    client: TestClient, scaffolded: str, model
) -> None:
    release = threading.Event()
    model(block=release)
    try:
        first = client.post("/api/construct", json={"subject": scaffolded}).json()

        second = client.post("/api/construct", json={"subject": scaffolded})
        assert second.status_code == 409
        assert second.json()["job"]["id"] == first["id"]
    finally:
        release.set()
    await_job(client, first["id"])


def test_a_construct_request_names_what_to_build(
    client: TestClient, subjects_root: Path
) -> None:
    assert client.post("/api/construct", json={}).status_code == 400
    assert client.post("/api/construct", json={"subject": "never-defined"}).status_code == 404
    assert client.post("/api/construct", json={"domain": "nope"}).status_code == 404
    assert client.post("/api/construct", json={"rel": "nope/x.ipynb"}).status_code == 404
    assert client.get("/api/construct/no-such-job").status_code == 404


def test_recent_jobs_are_listed_so_the_shell_can_re_attach(
    client: TestClient, scaffolded: str, model
) -> None:
    model()
    started = client.post("/api/construct", json={"subject": scaffolded}).json()
    await_job(client, started["id"])

    listed = client.get("/api/construct").json()
    assert listed["running"] is None
    assert listed["jobs"][0]["id"] == started["id"]
