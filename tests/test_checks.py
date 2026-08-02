"""Knowledge checks: a constructed notebook in, a gradable set of questions out.

The point of most of these is the same anti-fabrication contract the constructor has,
one level up: a check that could not actually grade a learner must never be written.
That is enforced by *running* each code check's reference solution, so "auto-graded"
cannot quietly mean "asserts nothing".

No test touches the network — every model call goes through an injected fake client.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import save_subject, subject_from_dict, topic_path  # noqa: E402
from praxis import checks as checks_mod  # noqa: E402
from praxis import llm  # noqa: E402
from praxis.checks import (  # noqa: E402
    GATED_SECTIONS,
    SYSTEM_PROMPT,
    CheckError,
    CheckOutcome,
    canonical_section,
    check_failures,
    checks_by_section,
    checks_for_topic,
    checks_from_reply,
    checks_path,
    checkset_failures,
    generate_checks,
    grade,
    load_checks,
    needs_checks,
    run_code_check,
    topic_checks_path,
)
from praxis.construct import construct_topic  # noqa: E402
from scaffold_notebooks import scaffold_subject  # noqa: E402

CURRICULUM = {
    "title": "Embedded Rust",
    "blurb": "Drive real hardware from Rust.",
    "modules": [
        {
            "title": "Foundations",
            "blurb": "The language guarantees that matter on a microcontroller.",
            "topics": [
                {"title": "Ownership and Borrowing", "slug": "ownership", "runnable": True},
                {"title": "Wiring a Dev Board", "slug": "wiring", "runnable": False,
                 "note": "needs hardware"},
            ],
        }
    ],
}


# --- the sample sets every test is built from -------------------------------


def choice(section: str, answer: int = 1) -> dict:
    return {
        "section": section,
        "kind": "choice",
        "prompt": f"In the context of {section.lower()}, which statement is correct?",
        "options": ["The first, which is wrong", "The second, which is right",
                    "The third, which is wrong"],
        "answer": answer,
        "explanation": "The second option is the one the section argues for.",
    }


def short(section: str) -> dict:
    return {
        "section": section,
        "kind": "short",
        "prompt": f"Explain, in your own words, what {section.lower()} means here.",
        "expected": "A correct answer names the mechanism, says when it applies, and "
                    "gives one consequence of getting it wrong.",
        "explanation": "The mechanism, its scope, and one consequence.",
    }


def code(section: str) -> dict:
    return {
        "section": section,
        "kind": "code",
        "prompt": "Write a function `owned(values)` that returns a copy of the list.",
        "starter": "def owned(values):\n    ...",
        "solution": "def owned(values):\n    return list(values)",
        "test": "original = [1, 2]\ncopy = owned(original)\n"
                "assert copy == original\nassert copy is not original",
        "explanation": "A copy compares equal but is a different object.",
    }


def good_checks(runnable: bool = True) -> list[dict]:
    """One check per gated section, and every kind the topic can carry."""
    items = [choice(GATED_SECTIONS[0]), short(GATED_SECTIONS[1])]
    items += [choice(s) for s in GATED_SECTIONS[2:]]
    if runnable:
        items.append(code(GATED_SECTIONS[3]))
    else:
        items.append(short(GATED_SECTIONS[3]))
    return items


def reply(items: list[dict]) -> str:
    return json.dumps({"checks": items})


class FakeClient:
    """An LLMClient stand-in: records each call, replies from a queue."""

    def __init__(self, *replies: str, model: str = "test-model"):
        self.replies, self.calls = list(replies), []
        self.config = llm.LLMConfig(provider="openai", model=model, api_key="k")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def subject():
    subj = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    save_subject(subj)
    scaffold_subject(subj)
    return subj


@pytest.fixture
def constructed(subject):
    """A module + topic whose notebook is already ✅ — the checks' real input."""
    from test_construct import FakeClient as CellClient  # the constructor's own fake
    from test_construct import good_cells, reply as cell_reply

    module, topic = subject.modules[0], subject.modules[0].topics[0]
    construct_topic(module, topic, client=CellClient(cell_reply(good_cells())),
                    checks=False)
    return module, topic


@pytest.fixture
def conceptual(subject):
    from test_construct import FakeClient as CellClient
    from test_construct import good_cells, reply as cell_reply

    module, topic = subject.modules[0], subject.modules[0].topics[1]
    construct_topic(module, topic,
                    client=CellClient(cell_reply(good_cells(runnable=False))),
                    checks=False)
    return module, topic


# --- the call ---------------------------------------------------------------


def test_the_notebook_and_the_sections_reach_the_model(constructed, subject):
    module, topic = constructed
    client = FakeClient(reply(good_checks()))

    generate_checks(module, topic, client=client, subject=subject)

    (call,) = client.calls
    assert call["system"] == SYSTEM_PROMPT
    assert "Ownership and Borrowing" in call["prompt"]
    assert "drive a microcontroller from Rust" in call["prompt"]
    for section in GATED_SECTIONS:
        assert section in call["prompt"]
    # The notebook itself is quoted, so the checks can only be about what it taught.
    assert "This section is written out in full" in call["prompt"]


def test_a_conceptual_topic_is_told_not_to_ask_for_code(conceptual):
    module, topic = conceptual
    client = FakeClient(reply(good_checks(runnable=False)))

    generate_checks(module, topic, client=client)

    assert "NO `code` checks" in client.calls[0]["prompt"]


# --- what it writes ---------------------------------------------------------


def test_a_generated_set_lands_beside_the_notebook_and_is_well_formed(constructed):
    module, topic = constructed
    result = generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    assert result.status == "generated" and result.ok
    assert result.path == topic_path(module, topic).with_name("ownership.checks.json")
    doc = json.loads(result.path.read_text())
    assert doc["version"] == 1
    assert (doc["slug"], doc["title"]) == ("ownership", "Ownership and Borrowing")
    assert doc["domain"] == module.dir and doc["runnable"] is True
    assert doc["generated_by"] == "test-model" and doc["generated"]
    assert checkset_failures(doc) == []
    assert result.count == len(doc["checks"]) == len(GATED_SECTIONS) + 1
    assert [c["id"] for c in doc["checks"]] == [
        f"ownership-{n:02d}" for n in range(1, len(doc["checks"]) + 1)
    ]


def test_every_gated_section_is_covered_by_at_least_one_check(constructed):
    module, topic = constructed
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    by_section = checks_by_section(checks_for_topic(module, topic))

    assert set(by_section) == set(GATED_SECTIONS)
    assert all(by_section[s] for s in GATED_SECTIONS)


def test_the_set_carries_a_mix_of_kinds(constructed):
    module, topic = constructed
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    kinds = {c["kind"] for c in checks_for_topic(module, topic)["checks"]}

    assert kinds == {"choice", "short", "code"}


def test_a_conceptual_topic_gets_no_code_checks(conceptual):
    module, topic = conceptual
    result = generate_checks(module, topic, client=FakeClient(reply(good_checks(False))))

    assert result.status == "generated"
    doc = checks_for_topic(module, topic)
    assert doc["runnable"] is False
    assert {c["kind"] for c in doc["checks"]} == {"choice", "short"}


# --- anti-fabrication -------------------------------------------------------


def _without(kind: str) -> list[dict]:
    return [c for c in good_checks() if c["kind"] != kind]


@pytest.mark.parametrize(
    "items, expected",
    [
        # A test that asserts nothing passes any answer at all.
        (_without("code") + [dict(code(GATED_SECTIONS[3]), test="print('ok')")],
         "must actually assert"),
        # A test whose own reference solution does not satisfy it.
        (_without("code") + [dict(code(GATED_SECTIONS[3]),
                                  solution="def owned(values):\n    return values")],
         "reference solution does not pass"),
        # No reference solution at all: nothing proves the check is passable.
        (_without("code") + [{k: v for k, v in code(GATED_SECTIONS[3]).items()
                              if k != "solution"}],
         "'solution' must hold a reference answer"),
        # An answer key pointing off the end of the options.
        (_without("choice")[:1] + [choice(s, answer=7) for s in GATED_SECTIONS],
         "0-based index"),
        # Two options, i.e. a coin flip.
        ([dict(choice(s), options=["yes", "no"]) for s in GATED_SECTIONS] + [short(GATED_SECTIONS[0])],
         ">= 3 options"),
        # A section nobody is tested on.
        ([c for c in good_checks() if c["section"] != GATED_SECTIONS[2]],
         "every rubric section needs at least one check"),
        # Every question the same kind — nothing exercises writing or code.
        ([choice(s) for s in GATED_SECTIONS], "mix of kinds"),
        # A marking key too vague to grade against.
        (_without("short") + [dict(short(GATED_SECTIONS[1]), expected="be right")],
         "'expected' must spell out"),
    ],
)
def test_a_set_that_could_not_grade_a_learner_is_never_written(constructed, items, expected):
    module, topic = constructed
    path = topic_checks_path(module, topic)

    result = generate_checks(module, topic, client=FakeClient(reply(items)), attempts=1)

    assert result.status == "failed" and not result.ok
    assert any(expected in f for f in result.failures), result.failures
    assert not path.exists()          # nothing on disk claims this topic is gated
    assert needs_checks(module, topic)


def test_checks_are_not_written_against_an_unconstructed_notebook(subject):
    """A scaffold teaches nothing, so there is nothing honest to test a learner on."""
    module, topic = subject.modules[0], subject.modules[0].topics[0]
    client = FakeClient(reply(good_checks()))

    result = generate_checks(module, topic, client=client)

    assert result.status == "failed"
    assert "not 'complete'" in result.detail
    assert client.calls == []                       # not even asked for
    assert not topic_checks_path(module, topic).exists()


def test_a_reply_that_is_not_a_check_set_fails_without_writing(constructed):
    module, topic = constructed

    result = generate_checks(module, topic, client=FakeClient("I'd rather not."),
                             attempts=1)

    assert result.status == "failed"
    assert "no JSON object" in result.detail
    assert not topic_checks_path(module, topic).exists()


def test_an_llm_error_is_reported_not_raised(constructed):
    module, topic = constructed

    class Boom(FakeClient):
        def complete(self, prompt, **kwargs):
            raise llm.LLMError("provider exploded")

    result = generate_checks(module, topic, client=Boom(), attempts=2)

    assert result.status == "failed" and "provider exploded" in result.detail


@pytest.mark.parametrize("data", [{}, {"checks": []}, {"checks": [{"prompt": ""}]}])
def test_an_empty_check_list_is_an_error(data, subject):
    with pytest.raises(CheckError):
        checks_from_reply(data, subject.modules[0].topics[0])


def test_write_false_grades_without_touching_the_disk(constructed):
    module, topic = constructed

    result = generate_checks(module, topic, client=FakeClient(reply(good_checks())),
                             write=False)

    assert result.status == "generated"
    assert not topic_checks_path(module, topic).exists()


# --- the repair loop --------------------------------------------------------


def test_a_failing_set_is_sent_back_with_the_validator_s_complaints(constructed):
    module, topic = constructed
    thin = [choice(GATED_SECTIONS[0])]
    client = FakeClient(reply(thin), reply(good_checks()))

    result = generate_checks(module, topic, client=client, attempts=3)

    assert result.status == "generated" and result.attempts == 2
    repair = client.calls[1]["prompt"]
    assert "FAILED validation" in repair
    assert "every rubric section needs at least one check" in repair
    assert "<draft>" in repair
    assert checkset_failures(checks_for_topic(module, topic)) == []


def test_attempts_are_bounded(constructed):
    module, topic = constructed
    client = FakeClient(reply([choice(GATED_SECTIONS[0])]))

    result = generate_checks(module, topic, client=client, attempts=2)

    assert result.status == "failed"
    assert result.attempts == 2 and len(client.calls) == 2


# --- idempotence ------------------------------------------------------------


def test_an_existing_set_is_skipped_not_rewritten(constructed):
    module, topic = constructed
    client = FakeClient(reply(good_checks()))
    first = generate_checks(module, topic, client=client)
    written = first.path.read_text()

    again = generate_checks(module, topic, client=client)

    assert again.status == "skipped" and again.ok
    assert again.detail == "already generated" and again.count == first.count
    assert len(client.calls) == 1                 # no second call, no tokens spent
    assert first.path.read_text() == written


def test_force_regenerates_an_existing_set(constructed):
    module, topic = constructed
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    rebuilt = generate_checks(
        module, topic, force=True,
        client=FakeClient(reply(good_checks()[:-1] + [
            dict(code(GATED_SECTIONS[3]), prompt="Write `owned(values)` — second pass."),
        ])),
    )

    assert rebuilt.status == "generated"
    assert "second pass" in rebuilt.path.read_text()


def test_a_set_that_no_longer_validates_is_regenerated(constructed):
    """A hand-edited or truncated file must not be trusted just because it exists."""
    module, topic = constructed
    path = topic_checks_path(module, topic)
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))
    doc = json.loads(path.read_text())
    doc["checks"] = doc["checks"][:1]              # a section is no longer covered
    path.write_text(json.dumps(doc))

    assert needs_checks(module, topic)
    result = generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    assert result.status == "generated"
    assert checkset_failures(json.loads(path.read_text())) == []


@pytest.mark.parametrize("doc", [
    None, {}, {"version": 99, "checks": []}, {"version": 1, "checks": "nope"},
])
def test_an_unusable_file_is_reported_as_missing(doc):
    assert checkset_failures(doc or {})


def test_a_missing_file_reads_as_none(tmp_path):
    assert load_checks(tmp_path / "nope.checks.json") is None
    (tmp_path / "bad.checks.json").write_text("not json")
    assert load_checks(tmp_path / "bad.checks.json") is None


def test_the_checks_file_sits_next_to_its_notebook():
    assert checks_path("a/b/ownership.ipynb") == Path("a/b/ownership.checks.json")


# --- normalizing what the model sent ----------------------------------------


@pytest.mark.parametrize("given, expected", [
    ("1. What & Why", "What & Why"),
    ("## 5. Worked Examples", "Worked Examples"),
    ("what and why", "What & Why"),
    ("Gotchas & Pitfalls", "Gotchas"),
    ("When to Use vs Alternatives", "When to Use"),
    ("Setup", ""),          # not a gated section
    ("", ""),
])
def test_a_section_heading_is_mapped_onto_the_rubric(given, expected):
    assert canonical_section(given) == expected


@pytest.mark.parametrize("kind", ["multiple-choice", "MCQ", "choice"])
def test_the_kinds_the_model_reaches_for_are_understood(kind, subject):
    items = [dict(choice(GATED_SECTIONS[0]), kind=kind)]
    assert checks_from_reply({"checks": items}, subject.modules[0].topics[0])[0][
        "kind"] == "choice"


@pytest.mark.parametrize("answer, expected", [
    (1, 1), ("1", 1), ("B", 1), ("The second, which is right", 1), ("nope", -1), (None, -1),
])
def test_an_answer_key_is_read_as_an_index(answer, expected, subject):
    items = [dict(choice(GATED_SECTIONS[0]), answer=answer)]
    parsed = checks_from_reply({"checks": items}, subject.modules[0].topics[0])[0]
    assert parsed["answer"] == expected


def test_a_check_with_no_question_is_dropped_not_kept(subject):
    items = [{"kind": "choice", "section": "What & Why"}, choice(GATED_SECTIONS[0])]

    parsed = checks_from_reply({"checks": items}, subject.modules[0].topics[0])

    assert len(parsed) == 1 and parsed[0]["id"] == "ownership-01"


# --- grading ----------------------------------------------------------------


def test_a_multiple_choice_answer_is_graded_against_the_key(subject):
    check = checks_from_reply({"checks": [choice(GATED_SECTIONS[0])]},
                              subject.modules[0].topics[0])[0]

    right = grade(check, 1)
    wrong = grade(check, 0)

    assert right.passed and not wrong.passed
    assert (right.kind, right.graded_by) == ("choice", "auto")
    assert right.check_id == "ownership-01" and right.graded
    assert wrong.answer == "0"          # what the learner picked, recorded
    assert "second option" in wrong.detail


def test_an_answer_that_is_not_an_option_fails(subject):
    check = checks_from_reply({"checks": [choice(GATED_SECTIONS[0])]},
                              subject.modules[0].topics[0])[0]

    outcome = grade(check, "the fourth one")

    assert not outcome.passed and "not one of the options" in outcome.detail


def test_a_code_answer_is_graded_by_actually_running_the_assertions(subject):
    check = checks_from_reply({"checks": [code(GATED_SECTIONS[3])]},
                              subject.modules[0].topics[0])[0]

    passing = grade(check, "def owned(values):\n    return list(values)")
    failing = grade(check, "def owned(values):\n    return values")

    assert passing.passed and passing.graded_by == "auto"
    assert not failing.passed
    assert "AssertionError" in failing.detail       # the real interpreter said so


def test_code_that_does_not_parse_fails_without_running(subject):
    check = checks_from_reply({"checks": [code(GATED_SECTIONS[3])]},
                              subject.modules[0].topics[0])[0]

    outcome = grade(check, "def owned(:\n    pass")

    assert not outcome.passed and "not valid Python" in outcome.detail


def test_an_empty_code_answer_cannot_pass(subject):
    check = checks_from_reply({"checks": [code(GATED_SECTIONS[3])]},
                              subject.modules[0].topics[0])[0]

    assert not grade(check, "").passed


def test_a_runaway_submission_is_cut_off_not_waited_on(subject):
    check = checks_from_reply({"checks": [code(GATED_SECTIONS[3])]},
                              subject.modules[0].topics[0])[0]

    ok, detail = run_code_check(check, "while True:\n    pass", timeout=2)

    assert not ok and "timed out" in detail


def test_a_short_answer_is_graded_by_the_model_with_the_answer_recorded(subject):
    check = checks_from_reply({"checks": [short(GATED_SECTIONS[1])]},
                              subject.modules[0].topics[0])[0]
    client = FakeClient(json.dumps({"passed": True, "feedback": "You named the mechanism."}))

    outcome = grade(check, "Ownership moves the value; the old binding is dead after.",
                    client=client)

    assert outcome.passed and outcome.graded_by == "test-model"
    assert outcome.detail == "You named the mechanism."
    # The learner's own words are what gets recorded — that is the audit trail.
    assert outcome.answer == "Ownership moves the value; the old binding is dead after."
    prompt = client.calls[0]["prompt"]
    assert "<learner-answer>" in prompt and "the old binding is dead" in prompt
    assert check["expected"] in prompt               # graded against the marking key


def test_a_short_answer_the_model_rejects_does_not_pass(subject):
    check = checks_from_reply({"checks": [short(GATED_SECTIONS[1])]},
                              subject.modules[0].topics[0])[0]
    client = FakeClient(json.dumps({"passed": False, "feedback": "You missed the scope."}))

    outcome = grade(check, "It is about memory I think.", client=client)

    assert not outcome.passed and outcome.detail == "You missed the scope."


def test_a_grader_that_will_not_answer_cleanly_is_an_error_not_a_pass(subject):
    check = checks_from_reply({"checks": [short(GATED_SECTIONS[1])]},
                              subject.modules[0].topics[0])[0]

    with pytest.raises(llm.LLMError):
        grade(check, "anything", client=FakeClient("sure, looks fine to me"))


def test_a_short_answer_cannot_be_graded_without_a_client(subject):
    check = checks_from_reply({"checks": [short(GATED_SECTIONS[1])]},
                              subject.modules[0].topics[0])[0]

    with pytest.raises(CheckError, match="graded by the model"):
        grade(check, "anything")


def test_an_outcome_serializes_for_storage():
    outcome = CheckOutcome(check_id="x-01", kind="choice", section="Setup",
                           passed=True, answer="1", detail="ok")

    assert outcome.to_dict()["check_id"] == "x-01"
    assert json.dumps(outcome.to_dict())      # a progress record must be storable


# --- one check at a time ----------------------------------------------------


def test_a_code_check_is_refused_on_a_topic_that_cannot_run_code(subject):
    check = checks_from_reply({"checks": [code(GATED_SECTIONS[3])]},
                              subject.modules[0].topics[1])[0]

    failures = check_failures(check, runnable=False)

    assert any("not Python-runnable" in f for f in failures)


def test_an_unknown_kind_is_named_in_the_failure(subject):
    items = [dict(choice(GATED_SECTIONS[0]), kind="essay-ish")]
    check = checks_from_reply({"checks": items}, subject.modules[0].topics[0])[0]

    assert any("unknown kind" in f for f in check_failures(check))


def test_the_structural_pass_does_not_run_any_code(constructed, monkeypatch):
    """Validating a stored set on load must stay cheap — no subprocess per check."""
    module, topic = constructed
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))

    def no_run(*args, **kwargs):
        raise AssertionError("the structural pass must not run code")

    monkeypatch.setattr(checks_mod, "run_code_check", no_run)

    assert checkset_failures(checks_for_topic(module, topic), verify_code=False) == []
    assert not needs_checks(module, topic)
