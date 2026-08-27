"""Author-in-the-loop gating: the shipped runner, driven from drafts on disk.

`praxis/authored.py` replaces exactly one thing — the call that asks a model for JSON —
and nothing else, so what is asserted here is that everything downstream still runs and
still refuses: `checkset_failures` with the reference solution executed in a subprocess,
the measured triviality rules, `publish_graded_cells` and `nbgrader validate`. A draft
that would be rejected from a model is rejected from a file, and the notebook is left
exactly as it was.

The one coupling the module has on the rest of the core is that a draft is looked up by
the topic title quoted in `build_prompt`'s output. That round trip is pinned below, so a
change to the prompt's shape fails a test instead of silently selecting a wrong draft.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import save_subject, subject_from_dict, topic_path  # noqa: E402
from praxis.authored import (  # noqa: E402
    DRAFT_SUFFIX,
    AuthoredClient,
    draft_path,
    load_draft,
    run_domain,
    topic_draft_path,
    topic_title_in,
)
from praxis.checks import build_prompt, checks_path, graded_cells, load_checks  # noqa: E402
from praxis.construct import construct_topic  # noqa: E402
from praxis.llm import LLMError  # noqa: E402
from scaffold_notebooks import scaffold_subject  # noqa: E402
from test_checks import code, good_checks  # noqa: E402
from test_construct import FakeClient, good_cells  # noqa: E402
from test_construct import reply as cell_reply  # noqa: E402

CURRICULUM = {
    "title": "Embedded Rust",
    "blurb": "Drive real hardware from Rust.",
    "modules": [
        {
            "title": "Foundations",
            "blurb": "The language guarantees that matter on a microcontroller.",
            "topics": [
                {"title": "Ownership and Borrowing", "slug": "ownership", "runnable": True},
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def domain():
    """One ✅ but ungated topic — the state a backfill exists to move."""
    subject = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    save_subject(subject)
    scaffold_subject(subject)
    module = subject.modules[0]
    construct_topic(module, module.topics[0], client=FakeClient(cell_reply(good_cells())),
                    checks=False)
    return module, subject


def write_draft(module, topic, checks) -> Path:
    path = topic_draft_path(module, topic)
    path.write_text(json.dumps({"checks": checks}))
    return path


# --- the one coupling -------------------------------------------------------


def test_the_topic_is_read_back_off_the_prompt_the_runner_builds(domain):
    """`build_prompt` quotes the title; the draft is found by it. Pin the round trip."""
    module, subject = domain
    topic = module.topics[0]
    nb = json.loads(topic_path(module, topic).read_text())

    prompt = build_prompt(module, topic, nb, subject=subject)

    assert topic_title_in(prompt) == topic.title


def test_a_prompt_naming_no_topic_selects_no_draft():
    assert topic_title_in("") == ""
    assert topic_title_in("write some checks, please") == ""


def test_a_draft_lives_beside_its_notebook(domain):
    module, topic = domain[0], domain[0].topics[0]

    path = topic_draft_path(module, topic)

    assert path == draft_path(topic_path(module, topic))
    assert path.name == topic.slug + DRAFT_SUFFIX
    assert path.parent == topic_path(module, topic).parent
    assert load_draft(path) is None          # nothing written yet


def test_an_unreadable_draft_reads_as_absent(tmp_path):
    path = tmp_path / "x.checks.draft.json"
    path.write_text("{not json")

    assert load_draft(path) is None


# --- the client -------------------------------------------------------------


def test_the_client_serves_the_draft_for_the_topic_it_was_asked_about(domain):
    module, subject = domain
    topic = module.topics[0]
    write_draft(module, topic, good_checks())
    nb = json.loads(topic_path(module, topic).read_text())

    client = AuthoredClient.for_domain(module, subject=subject)
    reply = client.complete(build_prompt(module, topic, nb, subject=subject))

    assert json.loads(reply)["checks"] == good_checks()
    assert client.asked == [topic.title]
    assert client.config.model == "hand-authored"


def test_a_topic_with_no_draft_fails_that_topic_and_names_the_file(domain):
    module, subject = domain
    topic = module.topics[0]
    nb = json.loads(topic_path(module, topic).read_text())
    client = AuthoredClient.for_domain(module, subject=subject)

    with pytest.raises(LLMError) as raised:
        client.complete(build_prompt(module, topic, nb, subject=subject))

    assert topic.title in str(raised.value)
    assert DRAFT_SUFFIX in str(raised.value)


# --- what lands, and what does not ------------------------------------------


def test_an_authored_draft_lands_as_a_gate_with_graded_cells(domain):
    module, subject = domain
    topic = module.topics[0]
    write_draft(module, topic, good_checks())

    results = run_domain(module, subject=subject, model="hand-authored:test")

    assert [r.slug for r in results] == [topic.slug]
    assert results[0].checks_ok, results[0].checks.failures
    stored = load_checks(checks_path(topic_path(module, topic)))
    assert stored["generated_by"] == "hand-authored:test"
    assert len(stored["checks"]) == len(good_checks())
    nb = json.loads(topic_path(module, topic).read_text())
    assert graded_cells(nb)


def test_a_draft_whose_solution_fails_its_own_test_is_not_written(domain):
    """The subprocess run is the load-bearing rule, and a file gets no exemption."""
    module, subject = domain
    topic = module.topics[0]
    broken = code("Worked Examples")
    broken["solution"] = "def owned(values):\n    return values"   # not a copy
    write_draft(module, topic, [c for c in good_checks() if c["kind"] != "code"] + [broken])
    before = topic_path(module, topic).read_bytes()

    results = run_domain(module, subject=subject)

    assert not results[0].checks_ok
    assert any("reference solution" in f for f in results[0].checks.failures)
    assert not checks_path(topic_path(module, topic)).is_file()
    assert topic_path(module, topic).read_bytes() == before


def test_a_draft_whose_test_passes_an_empty_submission_is_not_written(domain):
    """The measured triviality rules run on this path too — `quality` follows verify."""
    module, subject = domain
    topic = module.topics[0]
    trivial = code("Worked Examples")
    trivial["test"] = "assert True"
    write_draft(module, topic, [c for c in good_checks() if c["kind"] != "code"] + [trivial])

    results = run_domain(module, subject=subject)

    assert not results[0].checks_ok
    assert any("empty submission" in f for f in results[0].checks.failures)
    assert not checks_path(topic_path(module, topic)).is_file()


def test_a_draft_missing_a_section_is_not_written(domain):
    module, subject = domain
    topic = module.topics[0]
    write_draft(module, topic, good_checks()[:2])

    results = run_domain(module, subject=subject)

    assert not results[0].checks_ok
    assert any("rubric section" in f for f in results[0].checks.failures)
    assert not checks_path(topic_path(module, topic)).is_file()


def test_a_second_run_over_a_gated_domain_asks_the_author_for_nothing(domain):
    """Skip-if-gated is inherited from the backfill, so a resumed pass is free."""
    module, subject = domain
    topic = module.topics[0]
    write_draft(module, topic, good_checks())
    run_domain(module, subject=subject)
    stamp = topic_path(module, topic).read_bytes()

    again = run_domain(module, subject=subject)

    assert again == []
    assert topic_path(module, topic).read_bytes() == stamp
