"""Progression: what a learner has unlocked, and what still holds them back.

The gate is a *function* of recorded outcomes — nothing here stores "unlocked" — so
these tests are mostly about one rule and its consequences: a section opens only once
every check in every earlier section has a passing outcome, and the same rule one level
up orders the topics of a module.

No test touches a model: `choice` and `code` checks grade themselves, which is exactly
why the generated sets must carry them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis.checks import (  # noqa: E402
    GATED_SECTIONS,
    CheckOutcome,
    build_checkset,
    grade,
    learner_check,
)
from praxis.progress import (  # noqa: E402
    DEFAULT_LEARNER,
    empty_progress,
    gate_for,
    learner_id,
    load_progress,
    module_gates,
    progress_path,
    record_outcome,
    save_progress,
    section_gates,
    topic_outcomes,
    topic_progress,
    unlocked_sections,
)
from test_checks import CURRICULUM, choice, code, good_checks, short  # noqa: E402

REL = "subjects/embedded-rust/01-foundations/ownership.ipynb"


@pytest.fixture(autouse=True)
def progress_root(monkeypatch, tmp_path) -> Path:
    """Never write a learner's progress into the repo while testing."""
    monkeypatch.setenv("PRAXIS_PROGRESS_DIR", str(tmp_path / "progress"))
    return tmp_path / "progress"


def checkset(checks: list[dict] | None = None) -> dict:
    """A stored set, built the way praxis.checks builds one (ids and all)."""
    from curriculum import subject_from_dict

    subject = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    module, topic = subject.modules[0], subject.modules[0].topics[0]
    items = checks if checks is not None else good_checks()
    numbered = [dict(c, id=f"{topic.slug}-{i:02d}") for i, c in enumerate(items, 1)]
    return build_checkset(module, topic, numbered)


def pass_all(doc: dict, section: str, outcomes: dict) -> dict:
    """Record a passing outcome for every check in one section."""
    for check in doc["checks"]:
        if check["section"] == section:
            outcomes[check["id"]] = CheckOutcome(
                check_id=check["id"], kind=check["kind"], section=section,
                passed=True, answer="whatever the learner wrote",
            ).to_dict()
    return outcomes


# --- the rule ---------------------------------------------------------------


def test_only_the_first_section_is_open_to_a_new_learner() -> None:
    gates = section_gates(checkset(), {})

    assert [g.section for g in gates] == list(GATED_SECTIONS)
    assert [g.locked for g in gates] == [False] + [True] * (len(GATED_SECTIONS) - 1)
    assert unlocked_sections(checkset(), {}) == [GATED_SECTIONS[0]]


def test_passing_a_section_unlocks_exactly_the_next_one() -> None:
    doc = checkset()
    outcomes = pass_all(doc, GATED_SECTIONS[0], {})

    unlocked = unlocked_sections(doc, outcomes)

    assert unlocked == list(GATED_SECTIONS[:2])
    assert topic_progress(doc, outcomes)["next"] == GATED_SECTIONS[1]


def test_one_unpassed_check_keeps_the_section_and_everything_after_it_shut() -> None:
    """Two checks in the first section, one passed: no progress at all."""
    first = GATED_SECTIONS[0]
    doc = checkset(good_checks() + [choice(first, answer=0)])
    outcomes = pass_all(doc, first, {})
    # Un-pass the one we added back.
    outcomes[doc["checks"][-1]["id"]]["passed"] = False

    gates = section_gates(doc, outcomes)

    assert not gates[0].complete and gates[0].passed == 1
    assert all(g.locked for g in gates[1:])


def test_a_failed_retry_closes_a_section_that_had_opened() -> None:
    """An unlock is derived, not stored — so it can be lost again, honestly."""
    doc = checkset()
    outcomes = pass_all(doc, GATED_SECTIONS[0], {})
    assert not section_gates(doc, outcomes)[1].locked

    for outcome in outcomes.values():
        outcome["passed"] = False

    assert section_gates(doc, outcomes)[1].locked


def test_passing_everything_completes_the_topic() -> None:
    doc = checkset()
    outcomes: dict = {}
    for section in GATED_SECTIONS:
        pass_all(doc, section, outcomes)

    summary = topic_progress(doc, outcomes)

    assert summary["complete"] and summary["next"] == ""
    assert summary["passed"] == summary["n"] == len(doc["checks"])
    assert summary["unlocked"] == list(GATED_SECTIONS)


def test_a_notebook_with_no_checks_gates_nothing() -> None:
    """The seed library: 221 notebooks with no set beside them stay wide open."""
    assert section_gates(None, {}) == []
    assert topic_progress(None, {}) == {
        "gated": False, "passed": 0, "n": 0, "complete": False,
        "unlocked": [], "next": "",
    }


# --- what a locked section is allowed to hand over --------------------------


def test_a_locked_section_serves_no_questions_and_no_answer_key() -> None:
    doc = checkset()
    gates = section_gates(doc, {})

    first, second = gates[0].to_dict({}), gates[1].to_dict({})

    assert second["locked"] and second["checks"] == [] and second["n"] >= 1
    assert first["checks"] and not first["locked"]
    for served in first["checks"]:
        assert not {"answer", "solution", "test", "expected"} & served.keys()
        assert served["explanation"] == ""  # only after it has been graded


def test_an_answered_check_comes_back_with_its_explanation() -> None:
    check = choice(GATED_SECTIONS[0])
    outcome = grade(dict(check, id="x-01"), 1).to_dict()

    served = learner_check(dict(check, id="x-01"), outcome)

    assert served["answered"] and served["passed"]
    assert served["explanation"] == check["explanation"]
    assert served["options"] == check["options"]
    assert "answer" not in served


def test_a_code_check_hands_over_its_starter_but_not_its_solution() -> None:
    served = learner_check(dict(code(GATED_SECTIONS[0]), id="x-02"))

    assert served["starter"].startswith("def owned")
    assert "solution" not in served and "test" not in served


# --- grading is what moves the gate -----------------------------------------


def test_the_gate_moves_on_a_real_graded_answer_and_not_on_a_wrong_one() -> None:
    """End to end over the two auto-graded kinds: praxis.checks.grade() decides."""
    first, second = GATED_SECTIONS[0], GATED_SECTIONS[1]
    doc = checkset([choice(first), code(first), choice(second)]
                   + [choice(s) for s in GATED_SECTIONS[2:]]
                   + [short(GATED_SECTIONS[1])])
    outcomes: dict = {}

    for check in doc["checks"]:
        if check["section"] != first:
            continue
        wrong = 0 if check["kind"] == "choice" else "def owned(values):\n    return values"
        outcome = grade(check, wrong)
        assert not outcome.passed
        outcomes[outcome.check_id] = outcome.to_dict()
    assert section_gates(doc, outcomes)[1].locked

    for check in doc["checks"]:
        if check["section"] != first:
            continue
        right = check["answer"] if check["kind"] == "choice" else check["solution"]
        outcome = grade(check, right)
        assert outcome.passed
        outcomes[outcome.check_id] = outcome.to_dict()

    assert not section_gates(doc, outcomes)[1].locked


def test_gate_for_finds_the_section_a_check_belongs_to() -> None:
    doc = checkset()
    check = doc["checks"][-1]

    gate = gate_for(doc, {}, check["id"])

    assert gate is not None and gate.section == check["section"]
    assert gate_for(doc, {}, "no-such-check") is None


# --- persistence ------------------------------------------------------------


def test_an_outcome_survives_a_restart(progress_root: Path) -> None:
    outcome = CheckOutcome(check_id="ownership-01", kind="short", section=GATED_SECTIONS[0],
                           passed=True, answer="my own words", detail="covered the key",
                           graded_by="test-model")

    record_outcome(DEFAULT_LEARNER, REL, outcome)

    # A fresh read is all a restart is — nothing is cached in the process.
    stored = topic_outcomes(load_progress(DEFAULT_LEARNER), REL)["ownership-01"]
    assert stored == outcome.to_dict()
    assert stored["answer"] == "my own words"  # recorded verbatim, per the rubric
    assert json.loads(progress_path(DEFAULT_LEARNER).read_text())["version"] == 1


def test_a_retry_replaces_the_previous_answer() -> None:
    fail = CheckOutcome(check_id="ownership-01", kind="choice", section=GATED_SECTIONS[0],
                        passed=False, answer="0")
    record_outcome(DEFAULT_LEARNER, REL, fail)
    record_outcome(DEFAULT_LEARNER, REL, CheckOutcome(
        check_id="ownership-01", kind="choice", section=GATED_SECTIONS[0],
        passed=True, answer="1"))

    stored = topic_outcomes(load_progress(DEFAULT_LEARNER), REL)

    assert len(stored) == 1
    assert stored["ownership-01"]["passed"] and stored["ownership-01"]["answer"] == "1"


def test_two_learners_do_not_share_a_gate() -> None:
    record_outcome("Ada Lovelace", REL, CheckOutcome(
        check_id="ownership-01", kind="choice", section=GATED_SECTIONS[0],
        passed=True, answer="1"))

    assert topic_outcomes(load_progress("Ada Lovelace"), REL)
    assert topic_outcomes(load_progress(DEFAULT_LEARNER), REL) == {}
    assert progress_path("Ada Lovelace").name == "ada-lovelace.json"
    assert learner_id("  ") == DEFAULT_LEARNER


def test_a_corrupt_or_foreign_record_reads_as_a_fresh_start(progress_root: Path) -> None:
    """Never lock a learner out of the app over a file they can't see."""
    progress_root.mkdir(parents=True, exist_ok=True)
    (progress_root / "default.json").write_text("{not json")
    assert load_progress() == empty_progress()

    save_progress({"version": 99, "learner": DEFAULT_LEARNER, "topics": {"x": {}}})
    assert load_progress()["topics"] == {}


def test_progress_is_untouched_by_a_topic_it_has_never_seen() -> None:
    assert topic_outcomes(empty_progress(), "nothing/here.ipynb") == {}


# --- the same rule over a module's topics -----------------------------------


def test_a_module_unlocks_one_topic_at_a_time() -> None:
    doc = checkset()
    rels = ["m/a.ipynb", "m/b.ipynb", "m/c.ipynb"]
    docs = {rel: doc for rel in rels}

    fresh = module_gates(rels, docs, empty_progress())
    assert [fresh[r]["locked"] for r in rels] == [False, True, True]
    assert fresh["m/b.ipynb"]["blockedBy"] == "m/a.ipynb"

    progress = empty_progress()
    outcomes: dict = {}
    for section in GATED_SECTIONS:
        pass_all(doc, section, outcomes)
    progress["topics"]["m/a.ipynb"] = {"outcomes": outcomes}

    after = module_gates(rels, docs, progress)
    assert [after[r]["locked"] for r in rels] == [False, False, True]
    assert after["m/a.ipynb"]["complete"] and after["m/a.ipynb"]["gated"]


def test_ungated_topics_never_lock_what_follows_them() -> None:
    """The seed library is a module of topics with no checks — it must stay open."""
    rels = ["seed/a.ipynb", "seed/b.ipynb"]

    gates = module_gates(rels, {rel: None for rel in rels}, empty_progress())

    assert [gates[r]["locked"] for r in rels] == [False, False]
    assert not any(gates[r]["gated"] for r in rels)
