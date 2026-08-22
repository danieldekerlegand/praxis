"""The trust boundary: which process holds the answer key, and what may cross to a browser.

`docs/reference/gate-authority.md` is the prose contract and this is its enforcement. The
question only became sharp when JupyterLite became the runtime — a tutorial now *runs* in
a static site and a WebAssembly kernel the learner controls completely — but the answer is
older than that adoption and applies to every untrusted surface the app has: the webview,
the rendered notebook, and the site.

Nothing here calls a model and nothing here constructs: the seed library ships 24 real
gated notebooks with their answer keys beside them, which is a better subject than a
fixture anyway — it is what the app actually serves.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis import lite  # noqa: E402
from praxis.checks import (  # noqa: E402
    ANSWER_FIELDS,
    VERDICT_FIELDS,
    CheckError,
    checks_path,
    grade,
    learner_answer,
    learner_check,
    load_checks,
)
from praxis.progress import section_gates  # noqa: E402

NOTEBOOKS = ROOT / "notebooks"
DOC = ROOT / "docs" / "reference" / "gate-authority.md"

#: What a learner may never be handed, whatever surface they are looking at.
KEY_FIELDS = ("answer", "solution", "test", "expected")


def gated_seed_topics() -> list[tuple[str, Path, dict]]:
    """(rel, notebook path, answer key) for every gated notebook in the seed library."""
    out = []
    for key in sorted(NOTEBOOKS.rglob("*.checks.json")):
        nbp = Path(str(key)[: -len(".checks.json")] + ".ipynb")
        if nbp.is_file():
            out.append((nbp.relative_to(NOTEBOOKS).as_posix(), nbp, json.loads(key.read_text())))
    return out


GATED = gated_seed_topics()


@pytest.fixture(scope="module")
def gated_topics() -> list[tuple[str, Path, dict]]:
    assert GATED, "the seed library ships gated notebooks; none were found"
    return GATED


def visible_text(page: str) -> str:
    """What a reader can see in a rendered page, tags and entities resolved.

    A plain substring search over HTML misses code: nbconvert's classic template
    highlights it into `<span>`s, so `assert x == 3` is never one string in the source.
    Stripping the markup first is what makes "is the answer on this page?" measurable.
    """
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", body)))


def squashed(text: str) -> str:
    return " ".join(str(text).split())


# --- the document ------------------------------------------------------------


def test_the_boundary_is_stated_in_one_place_and_that_place_is_reachable():
    """docs/README.md's rule: a document not linked there does not exist."""
    assert "reference/gate-authority.md" in (ROOT / "docs" / "README.md").read_text()
    doc = DOC.read_text()
    # The claim itself, and each mechanism a reader would go looking for.
    assert "answer key is held by the Python core behind `launcher/app.py`" in doc
    for named in ("learner_check", "learner_answer", "browser_notebook", "run_code_check",
                  "section_gates", "423", "503", "400", "403"):
        assert named in doc, f"the contract does not mention {named}"
    # And the one thing a reader must not be able to conclude.
    assert "never a grader" in doc, "the browser kernel's role is not stated"


def test_the_runtime_doc_defers_rather_than_restating_it():
    """Two statements of the same boundary would drift; jupyterlite.md points here."""
    runtime = (ROOT / "docs" / "reference" / "jupyterlite.md").read_text()
    assert "gate-authority.md" in runtime


# --- what may cross, going out -----------------------------------------------


def test_learner_check_never_emits_the_key_for_any_check_in_the_seed_library(gated_topics):
    """Measured over every shipped check rather than a constructed example."""
    checked = 0
    for _rel, _nbp, doc in gated_topics:
        for check in doc["checks"]:
            view = learner_check(check)
            assert not set(KEY_FIELDS) & view.keys(), check.get("id")
            assert view["explanation"] == "", "an ungraded check gives its answer away"
            # The question itself does cross — that is the point of a check.
            assert view["prompt"] == check["prompt"]
            for field in KEY_FIELDS:
                value = squashed(check.get(field, ""))
                if len(value) > 12:  # a one-word key is a word the prompt may use
                    assert value not in squashed(json.dumps(view)), f"{field} leaked"
            checked += 1
    assert checked >= 24, checked


def test_a_locked_section_serves_no_question_text(gated_topics):
    """Not a disabled button and not an empty list of answers — no questions at all."""
    for _rel, _nbp, doc in gated_topics:
        gates = [g.to_dict({}) for g in section_gates(doc, {})]
        locked = [g for g in gates if g["locked"]]
        assert locked, "a fresh learner has locked sections"
        served = squashed(json.dumps(gates))
        for gate, source in zip(gates, section_gates(doc, {})):
            if not gate["locked"]:
                continue
            assert gate["checks"] == [] and gate["n"] >= 1
            for check in source.checks:
                assert squashed(check["prompt"]) not in served, gate["section"]


def test_the_notebook_that_crosses_carries_no_graded_region(gated_topics):
    """The same filter for both untrusted surfaces — the site, and `/render`.

    Measured on the shipped library: 168 graded cells across the 24 gated notebooks, and
    every one of them is dropped. `checks.graded_cells()` alone would not do it — the
    companion autograder-tests cell nbgrader releases carries no praxis namespace, and
    its assertions *are* the answer.
    """
    graded = 0
    for _rel, nbp, _doc in gated_topics:
        nb = json.loads(nbp.read_text())
        graded += sum(1 for cell in nb["cells"] if lite._graded(cell))
        served = lite.browser_notebook(nb)
        assert lite.leak_failures(served, nbp.name) == []
        assert not [cell for cell in served["cells"] if lite._graded(cell)]
    assert graded >= 100, graded


def test_a_code_checks_hidden_test_is_in_nothing_that_crosses(gated_topics):
    """Auto-grading is worth nothing if the assertions travel with the question."""
    tested = 0
    for _rel, nbp, doc in gated_topics:
        served = squashed(json.dumps(lite.browser_notebook(json.loads(nbp.read_text()))))
        for check in doc["checks"]:
            test = squashed(check.get("test", ""))
            if not test:
                continue
            tested += 1
            assert test not in served, f"{check['id']}'s test is in the served notebook"
            assert test not in squashed(json.dumps(learner_check(check)))
    assert tested >= 1, "no code checks in the seed library to measure"


# --- what may cross, coming in -----------------------------------------------


def test_learner_answer_reads_only_what_a_learner_authors():
    assert ANSWER_FIELDS == ("check_id", "answer")
    assert learner_answer({"check_id": " c1 ", "answer": "mine"}) == ("c1", "mine")
    assert learner_answer({"checkId": "c1", "answer": 2}) == ("c1", 2)
    # An unknown field is not a verdict; it is simply not read.
    assert learner_answer({"check_id": "c1", "answer": "a", "draft": True}) == ("c1", "a")
    with pytest.raises(CheckError):
        learner_answer(["c1", "mine"])


@pytest.mark.parametrize("field", VERDICT_FIELDS)
def test_a_submission_carrying_a_verdict_is_refused_rather_than_ignored(field):
    """A client that sends a verdict believes it grades. Saying so beats dropping it."""
    with pytest.raises(CheckError) as exc:
        learner_answer({"check_id": "c1", "answer": "mine", field: True})
    assert field in str(exc.value)


def test_the_graders_own_reply_cannot_be_posted_back_as_one():
    """The response's shape is the obvious thing to forge, so every key of it is refused."""
    reply = {"outcome": {"passed": True}, "state": {"locked": False, "unlocked": ["x"]}}
    for field in reply:
        assert field in VERDICT_FIELDS, f"a client could echo {field} back unrefused"
    with pytest.raises(CheckError):
        learner_answer({"check_id": "c1", "answer": "mine", **reply})


# --- where grading happens ---------------------------------------------------


def test_a_short_answer_cannot_be_graded_without_the_trusted_processs_key():
    """The one path that needs a model — and it is refused, never defaulted to a pass."""
    with pytest.raises(CheckError):
        grade({"kind": "short", "prompt": "why?", "expected": "because"}, "because")


def test_an_auto_graded_code_check_runs_the_submission_here(gated_topics):
    """`run_code_check` is a subprocess of *this* interpreter, not the browser kernel."""
    check = next((c for _r, _p, d in gated_topics for c in d["checks"]
                  if c.get("kind") == "code" and c.get("test")), None)
    if check is None:
        pytest.skip("no code check in the seed library")
    assert grade(check, check["solution"]).passed is True
    assert grade(check, "pass").passed is False


# --- the frontend derives nothing --------------------------------------------

UI_SOURCES = sorted((ROOT / "ui" / "src").glob("*.ts")) + sorted((ROOT / "ui" / "src").glob("*.tsx"))


def test_the_browser_holds_no_unlock_logic():
    """`locked` is read in the webview and never produced there."""
    assert UI_SOURCES
    for path in UI_SOURCES:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\b(un)?locked\s*=[^=]", line) or "setLocked" in line:
                pytest.fail(f"{path.name}:{number} derives a lock: {line.strip()}")


def test_the_browser_never_reaches_for_an_answer_key_or_the_gates_rule():
    """The two names that would mean a second definition of the gate had appeared."""
    for path in UI_SOURCES:
        body = path.read_text()
        assert ".checks.json" not in body, f"{path.name} fetches an answer key"
        assert "GATED_SECTIONS" not in body, f"{path.name} holds the section order"
