"""Gate quality: does a written gate actually ask the learner anything?

Every gate audited here has already cleared the two bars that ship — the write-path
grader (`checkset_failures`, reference solution run against its own test) and, for the
cells in the notebook, `nbgrader validate`. So each test below builds a set that those
would accept and asserts that the audit still catches what neither of them can see: an
answer given away in its own question, a marking key copied out of the page, a test that
asserts nothing about the learner's answer, and the same question asked twice.

The last test is the regression guard the band is measured against: the 24 hand-built
seed gates must come back clean, or the bar is not the bar the seeds hold.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis.checks import GATED_SECTIONS  # noqa: E402
from praxis.gateaudit import (  # noqa: E402
    audit_checkset,
    audit_gates,
    body_text,
    quality_failures,
    set_quality_failures,
)

BODY = (
    "A budget is spent where the model is most uncertain, not where it is cheapest to "
    "measure, because a confident region tells you nothing you did not already know. "
    "The sampling rate therefore follows the variance of the estimate rather than the "
    "size of the slice, and the two come apart badly on a long tail.\n"
)


def notebook(*, gated_cell: str = "") -> dict:
    cells = [{"cell_type": "markdown", "metadata": {}, "source": BODY}]
    if gated_cell:
        cells.append({
            "cell_type": "markdown",
            "id": "g-01",
            "metadata": {"praxis": {"extension": "checks", "kind": "short",
                                    "grade_id": "g-01"}},
            "source": [gated_cell],
        })
    return {"metadata": {"praxis": {"status": "complete", "runnable": True}},
            "cells": cells, "nbformat": 4, "nbformat_minor": 5}


# --- a set that asks something ----------------------------------------------

GENUINE = [
    {
        "section": "What & Why",
        "kind": "choice",
        "prompt": "Two slices of an eval set cost the same to label. Which one earns "
                  "the next hundred annotations?",
        "options": [
            "The slice whose estimate has the widest confidence interval",
            "The slice with the most examples already labelled",
            "The slice the product team asks about most often",
            "The slice with the highest average score so far",
        ],
        "answer": 0,
        "explanation": "Spend where the estimate is loosest.",
    },
    {
        "section": "Mental Model",
        "kind": "short",
        "prompt": "Your dashboard reports 91% on a suite whose slices are wildly "
                  "different sizes. Explain to a sceptical colleague why that single "
                  "number can rise while every slice gets worse.",
        "expected": "A correct answer must describe Simpson's paradox concretely: the "
                    "headline is a weighted mean, so a shift in the mix of slice sizes "
                    "can move it in the opposite direction to every component. It must "
                    "say that per-slice numbers and their weights have to be reported "
                    "beside the aggregate for it to mean anything.",
        "explanation": "A weighted mean can move against all of its parts.",
    },
    {
        "section": "Key Concepts",
        "kind": "choice",
        "prompt": "A regression suite is rerun nightly and one flaky item flips freely. "
                  "What does that do to a reported delta of half a point?",
        "options": [
            "It puts the delta inside the run-to-run noise, so nothing has been shown",
            "It biases the delta downward by exactly the flake rate",
            "It has no effect once the suite is large enough",
            "It invalidates only the flaky item's own contribution",
        ],
        "answer": 0,
        "explanation": "Noise floor first, then deltas.",
    },
    {
        "section": "Worked Examples",
        "kind": "code",
        "prompt": "Write `weighted_score(slices)` where `slices` is a list of "
                  "`(mean, count)` pairs. Return the count-weighted mean, and 0.0 for "
                  "an empty list. Standard library only.",
        "starter": "def weighted_score(slices):\n    ...\n",
        "solution": "def weighted_score(slices):\n"
                    "    total = sum(n for _, n in slices)\n"
                    "    if not total:\n"
                    "        return 0.0\n"
                    "    return sum(m * n for m, n in slices) / total\n",
        "test": "assert weighted_score([]) == 0.0\n"
                "assert abs(weighted_score([(1.0, 1), (0.0, 3)]) - 0.25) < 1e-9\n"
                "assert abs(weighted_score([(0.5, 10)]) - 0.5) < 1e-9\n",
        "explanation": "Weight by count, and do not divide by zero.",
    },
    {
        "section": "Gotchas",
        "kind": "short",
        "prompt": "You raise the sampling rate on your worst slice and the headline "
                  "falls. Name the mistake a reader makes here, and what you would put "
                  "on the chart to stop them making it.",
        "expected": "A correct answer must say that the drop is a change in the "
                    "composition of the sample rather than a change in quality, so it "
                    "is not evidence of a regression. It must propose showing the "
                    "per-slice series and the weights over time, so that a mix shift is "
                    "visibly distinct from a quality shift.",
        "explanation": "Mix shift is not a regression.",
    },
    {
        "section": "When to Use",
        "kind": "choice",
        "prompt": "When is a cheap proxy metric the right thing to gate a merge on?",
        "options": [
            "When it is validated against the expensive measure on a labelled sample "
            "and reported with that agreement",
            "Whenever the expensive measure takes longer than the CI budget allows",
            "Only for models smaller than the one it was calibrated on",
            "Never — a proxy can only be used for monitoring",
        ],
        "answer": 0,
        "explanation": "A proxy is worth what its agreement number says it is.",
    },
]


def checkset(checks: list[dict], *, slug: str = "eval-budget") -> dict:
    numbered = []
    for index, raw in enumerate(checks, 1):
        check = dict(raw)
        check.setdefault("id", f"{slug}-{index:02d}")
        numbered.append(check)
    return {
        "version": 1,
        "slug": slug,
        "title": "Spending an Eval Budget",
        "domain": "12-model-evaluation",
        "runnable": True,
        "generated": "2026-08-22T00:00:00+00:00",
        "generated_by": "test",
        "sections": list(GATED_SECTIONS),
        "praxis": {"extension": "checks", "version": 1, "kinds": ["choice", "short"]},
        "checks": numbered,
    }


def write_gate(root: Path, doc: dict, nb: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{doc['slug']}.checks.json"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    (root / f"{doc['slug']}.ipynb").write_text(json.dumps(nb if nb else notebook()))
    return path


def only(check: dict, **kwargs) -> list[str]:
    return quality_failures(check, **kwargs)


# --- the genuine set is not flagged -----------------------------------------


def test_genuine_gate_passes_the_audit(tmp_path):
    path = write_gate(tmp_path, checkset(GENUINE))
    before = path.read_bytes()

    report = audit_checkset(path, root=tmp_path)

    assert report["status"] == "healthy", report["findings"]
    assert report["checkset_failures"] == []
    assert report["quality_failures"] == []
    assert report["counts"] == {"choice": 3, "code": 1, "short": 2}
    assert path.read_bytes() == before


# --- an answer given away in its own question -------------------------------


def test_choice_whose_prompt_spells_out_its_answer_is_flagged():
    check = {
        "id": "given-away-01",
        "section": "Key Concepts",
        "kind": "choice",
        "prompt": "Because a chance-corrected statistic such as Cohen's kappa accounts "
                  "for agreement that a majority-class guesser would reach anyway, what "
                  "should you report beside raw agreement?",
        "options": [
            "A chance-corrected statistic such as Cohen's kappa, which accounts for "
            "agreement a majority-class guesser reaches anyway",
            "The number of annotators",
            "The wall-clock cost of the labelling run",
            "The random seed",
        ],
        "answer": 0,
        "explanation": "Kappa.",
    }

    failures = only(check)

    assert len(failures) == 1
    assert failures[0].startswith("given-away-01: ")
    assert "gives its own answer away" in failures[0]
    assert "%" in failures[0]


def test_choice_that_merely_shares_its_subject_vocabulary_is_not_flagged():
    assert only(GENUINE[0] | {"id": "genuine-01"}) == []
    assert only(GENUINE[2] | {"id": "genuine-03"}) == []


def test_short_whose_prompt_quotes_its_marking_key_is_flagged():
    key = ("A correct answer must say that the headline is a weighted mean over slices "
           "of different sizes, so a shift in the mix of those sizes moves it against "
           "every component.")
    check = {
        "id": "quoted-02",
        "section": "Mental Model",
        "kind": "short",
        "prompt": "Explain why " + key.split("must say that ")[1],
        "expected": key,
        "explanation": "Simpson's paradox.",
    }

    failures = only(check)

    assert len(failures) == 1
    assert "contains its own marking key" in failures[0]
    assert failures[0].startswith("quoted-02: ")


# --- an answer the page already gives ---------------------------------------


def test_short_answered_verbatim_by_the_notebook_body_is_flagged():
    check = {
        "id": "copied-02",
        "section": "Mental Model",
        "kind": "short",
        "prompt": "Where in an eval suite should the next hundred annotations go, and "
                  "what does the sampling rate follow?",
        "expected": BODY,
        "explanation": "It is the first paragraph of the notebook.",
    }

    assert only(check) == []  # nothing wrong with it until you read the notebook
    failures = only(check, notebook=BODY)

    assert len(failures) == 1
    assert "copied out of the notebook" in failures[0]
    assert "searching the page" in failures[0]


def test_a_question_is_not_evidence_for_itself():
    """The prompt is published into the notebook, so the body must exclude it."""
    prompt = GENUINE[1]["prompt"]
    nb = notebook(gated_cell=prompt + "\n" + GENUINE[1]["expected"])

    body = body_text(nb)

    assert prompt not in body
    assert BODY.strip() in body
    assert set_quality_failures(checkset(GENUINE), notebook=body) == []


# --- a test that asserts nothing about the answer ---------------------------


def test_code_check_whose_test_passes_an_empty_submission_is_flagged():
    check = {
        "id": "hollow-04",
        "section": "Worked Examples",
        "kind": "code",
        "prompt": "Write `weighted_score(slices)` returning the count-weighted mean.",
        "starter": "def weighted_score(slices):\n    ...\n",
        "solution": "def weighted_score(slices):\n    return 0.0\n",
        "test": "assert True  # the learner tried\n",
        "explanation": "It asserts nothing.",
    }

    failures = only(check)

    assert len(failures) == 1
    assert "passes an empty submission" in failures[0]
    assert "asserts nothing about the learner's answer" in failures[0]


def test_code_check_whose_test_passes_the_starter_stub_is_flagged():
    check = {
        "id": "stub-04",
        "section": "Worked Examples",
        "kind": "code",
        "prompt": "Write `weighted_score(slices)` returning the count-weighted mean.",
        "starter": "def weighted_score(slices):\n    return None\n",
        "solution": "def weighted_score(slices):\n"
                    "    return sum(m * n for m, n in slices) / sum(n for _, n in slices)\n",
        "test": "assert weighted_score([(1.0, 1)]) is not weighted_score\n",
        "explanation": "True of the stub as well as of a real answer.",
    }

    failures = only(check)

    assert len(failures) == 1
    assert "passes the starter stub unchanged" in failures[0]


def test_the_genuine_code_check_is_not_flagged_and_the_run_is_skippable():
    assert only(GENUINE[3] | {"id": "genuine-04"}) == []
    assert only({"id": "hollow", "section": "Worked Examples", "kind": "code",
                 "prompt": "x", "starter": "", "solution": "", "test": "assert True\n"},
                verify_code=False) == []


# --- the same question twice ------------------------------------------------


def test_near_identical_prompts_across_sections_are_flagged():
    template = ("Which statement best describes how a weighted eval headline responds "
                "to a change in slice mix, in the context of {}?")
    doc = checkset([
        dict(GENUINE[0], section="What & Why", prompt=template.format("what and why")),
        dict(GENUINE[2], section="Gotchas", prompt=template.format("gotchas")),
    ])

    failures = set_quality_failures(doc, verify_code=False)

    assert len(failures) == 1
    assert "near-identical" in failures[0]
    assert "across sections" in failures[0]
    assert failures[0].startswith("eval-budget-01 and eval-budget-02: ")


def test_distinct_questions_are_not_called_duplicates():
    assert set_quality_failures(checkset(GENUINE), verify_code=False) == []


# --- the two halves stay separate -------------------------------------------


def test_gradability_is_reported_by_the_shipped_grader_not_re_implemented(tmp_path):
    """A set missing a section is the write-path grader's complaint, not this band's."""
    path = write_gate(tmp_path, checkset(GENUINE[:2]))

    report = audit_checkset(path, root=tmp_path)

    assert report["status"] == "flagged"
    assert any("nothing tests" in f for f in report["checkset_failures"])
    assert report["quality_failures"] == []


def test_audit_gates_walks_a_tree_and_reports_each_gate(tmp_path):
    write_gate(tmp_path / "a", checkset(GENUINE))
    hollow = dict(GENUINE[3], test="assert True\n",
                  solution="def weighted_score(slices):\n    return 0.0\n")
    write_gate(tmp_path / "b", checkset(GENUINE[:3] + [hollow] + GENUINE[4:],
                                        slug="hollow-gate"))

    report = audit_gates(tmp_path)

    assert report["gates"] == 2
    assert report["checks"] == 12
    assert report["flagged"] == 1
    flagged = [r for r in report["reports"] if r["status"] == "flagged"]
    assert flagged[0]["checks"] == "b/hollow-gate.checks.json"
    assert flagged[0]["notebook"] == "b/hollow-gate.ipynb"
    assert any("passes an empty submission" in f for f in flagged[0]["quality_failures"])


def test_unreadable_checkset_is_reported_not_raised(tmp_path):
    path = tmp_path / "broken.checks.json"
    path.write_text("{not json")

    report = audit_checkset(path, root=tmp_path)

    assert report["status"] == "unreadable"
    assert report["findings"]


# --- the bar the seed library already holds ---------------------------------


def test_every_shipped_seed_gate_is_clean():
    """Every gate on disk is clean, and the corpus only ever grows.

    A floor, not an equality: the gating backfill (praxis/backfill.py) exists to add
    gates, so pinning the count would make the tool that raises coverage fail the
    suite. The 24 hand-built gates the thresholds were measured against are the floor;
    what stays exact is that NOTHING is flagged, which is the property the numbers
    were only ever standing in for.
    """
    report = audit_gates(ROOT / "notebooks")

    assert report["gates"] >= 24
    assert report["checks"] >= 144
    flagged = {r["checks"]: r["findings"] for r in report["reports"]
               if r["status"] != "healthy"}
    assert flagged == {}
