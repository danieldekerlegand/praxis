"""Gates written before the bar existed: re-audited, and regenerated only by policy.

The write path was tightened after these gates were written, and the cheap load path
deliberately does not re-judge them — so the only thing that can say whether a gate on
disk still meets the bar is an explicit pass, which is what is asserted here. Two
properties carry the band: a re-audit **writes nothing** (a flagged gate stays exactly
where it is, with the grader's own sentences), and a forced regeneration goes through
the shipped write path, so a candidate that fails the tightened bar leaves the existing
gate byte-identical rather than stripping the notebook of the gate it had.

The last test is the regression guard: every gate the library ships was written before
the tightening and must still hold it, or the bar is not the bar the seeds hold.

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
from praxis.backfill import is_gated  # noqa: E402
from praxis.checks import (  # noqa: E402
    checks_path,
    checkset_failures,
    generate_checks,
    graded_cells,
    load_checks,
    nbgrader_validate,
    needs_checks,
)
from praxis.construct import construct_topic  # noqa: E402
from praxis.gateaudit import body_text  # noqa: E402
from praxis.regate import (  # noqa: E402
    FLAGGED_FOR_HUMAN,
    FORCE_REGENERATE,
    HOLDS,
    bar_failures,
    reaudit_gate,
    reaudit_gates,
    regate_gate,
)
from scaffold_notebooks import scaffold_subject  # noqa: E402
from test_checks import CURRICULUM, FakeClient, good_checks, reply  # noqa: E402


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    """Every write lands in a temp dir — never the developer's notebooks/."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def gated():
    """A ✅ notebook with a gate on it — written the way the backfill writes one."""
    from test_construct import FakeClient as CellClient
    from test_construct import good_cells, reply as cell_reply

    subject = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    save_subject(subject)
    scaffold_subject(subject)
    module, topic = subject.modules[0], subject.modules[0].topics[0]
    construct_topic(module, topic, client=CellClient(cell_reply(good_cells())),
                    checks=False)
    generate_checks(module, topic, client=FakeClient(reply(good_checks())))
    return module, topic


def hollow_checks() -> list[dict]:
    """A set the *old* bar accepts: gradable in every way, and asks nothing real.

    The reference solution still passes its own test — which is all generation used to
    prove — but so does an empty submission, so the check grades no one.
    """
    items = [dict(c) for c in good_checks()]
    for check in items:
        if check["kind"] == "code":
            check["test"] = "assert True  # the learner tried\n"
    return items


def pre_tightening(module, topic) -> tuple[Path, Path, bytes, bytes]:
    """Rewrite the gate on disk as one written before the bar existed."""
    notebook = topic_path(module, topic)
    sidecar = checks_path(notebook)
    doc = load_checks(sidecar)
    doc["checks"] = [
        dict(check, test="assert True  # the learner tried\n")
        if check["kind"] == "code" else check
        for check in doc["checks"]
    ]
    sidecar.write_text(json.dumps(doc, indent=2) + "\n")
    return notebook, sidecar, notebook.read_bytes(), sidecar.read_bytes()


# --- what a re-audit measures, and what it leaves alone ----------------------


def test_a_gate_that_still_holds_the_bar_is_reported_as_holding(gated):
    module, topic = gated
    sidecar = checks_path(topic_path(module, topic))
    before = sidecar.read_bytes()

    result = reaudit_gate(sidecar)

    assert result.outcome == HOLDS and result.ok
    assert result.failures == ()
    assert result.slug == "ownership"
    assert result.notebook == "ownership.ipynb"
    assert sidecar.read_bytes() == before


def test_a_pre_tightening_gate_is_flagged_with_the_graders_own_sentence(gated):
    module, topic = gated
    notebook, sidecar, nb_before, checks_before = pre_tightening(module, topic)

    result = reaudit_gate(sidecar)

    assert result.outcome == FLAGGED_FOR_HUMAN and not result.ok
    (failure,) = result.failures
    assert "passes an empty submission" in failure
    assert "asserts nothing about the learner's answer" in failure
    # It fails ONLY the new rules — the shipped gradability half still accepts it,
    # which is what "written before the tightening landed" means on disk.
    assert checkset_failures(load_checks(sidecar), quality=False) == []
    # Nothing moved, and the notebook is still gated rather than left open.
    assert sidecar.read_bytes() == checks_before
    assert notebook.read_bytes() == nb_before
    assert not needs_checks(module, topic) and is_gated(module, topic)


def test_the_re_audit_measures_with_the_write_paths_own_grader(gated):
    """No parallel grader: the sentences are `checkset_failures`' own, one call."""
    module, topic = gated
    _, sidecar, _, _ = pre_tightening(module, topic)
    doc = load_checks(sidecar)
    nb = json.loads(topic_path(module, topic).read_text())

    assert list(reaudit_gate(sidecar).failures) == bar_failures(doc, nb)
    assert bar_failures(doc, nb) == checkset_failures(doc, notebook=body_text(nb))


def test_the_structural_half_can_be_run_without_the_subprocesses(gated):
    module, topic = gated
    _, sidecar, _, _ = pre_tightening(module, topic)

    assert reaudit_gate(sidecar, verify_code=False).outcome == HOLDS
    assert reaudit_gate(sidecar).outcome == FLAGGED_FOR_HUMAN


def test_an_unreadable_gate_is_flagged_not_raised(tmp_path):
    path = tmp_path / "broken.checks.json"
    path.write_text("{not json")

    result = reaudit_gate(path, root=tmp_path)

    assert result.outcome == FLAGGED_FOR_HUMAN
    assert result.failures == ("the checks file does not hold a JSON object",)


# --- regeneration is explicit, per gate, and through the shipped write path ---


def test_a_holding_gate_is_never_a_regeneration_target(gated):
    module, topic = gated
    sidecar = checks_path(topic_path(module, topic))
    before = sidecar.read_bytes()
    client = FakeClient(reply(good_checks()))

    result = regate_gate(sidecar, force=True, client=client)

    assert result.outcome == HOLDS
    assert client.calls == []          # a re-audit that holds costs no model call
    assert sidecar.read_bytes() == before


def test_a_flagged_gate_is_not_rewritten_without_the_explicit_force(gated):
    module, topic = gated
    notebook, sidecar, nb_before, checks_before = pre_tightening(module, topic)
    client = FakeClient(reply(good_checks()))

    result = regate_gate(sidecar, client=client)

    assert result.outcome == FLAGGED_FOR_HUMAN
    assert result.generation is None and client.calls == []
    assert (notebook.read_bytes(), sidecar.read_bytes()) == (nb_before, checks_before)


def test_a_regeneration_that_fails_the_tightened_bar_is_never_written(gated):
    module, topic = gated
    notebook, sidecar, nb_before, checks_before = pre_tightening(module, topic)
    client = FakeClient(reply(hollow_checks()))

    result = regate_gate(sidecar, force=True, client=client, attempts=1)

    assert result.outcome == FORCE_REGENERATE and not result.ok
    assert result.generation.status == "failed"
    assert any("passes an empty submission" in f for f in result.generation.failures)
    # The existing gate survives byte-identical: the notebook keeps the gate it had
    # rather than being left ungated by an attempt to improve it.
    assert (notebook.read_bytes(), sidecar.read_bytes()) == (nb_before, checks_before)
    assert is_gated(module, topic)


def test_an_explicit_regeneration_replaces_it_only_with_one_that_passes(gated):
    module, topic = gated
    notebook, sidecar, _, checks_before = pre_tightening(module, topic)
    client = FakeClient(reply(good_checks()))

    result = regate_gate(sidecar, force=True, client=client, attempts=1)

    assert result.outcome == FORCE_REGENERATE and result.ok
    assert result.generation.status == "generated"
    assert sidecar.read_bytes() != checks_before
    assert reaudit_gate(sidecar).outcome == HOLDS
    # The gate the learner meets is republished too, and is what nbgrader released.
    doc = load_checks(sidecar)
    cells = graded_cells(json.loads(notebook.read_text()))
    assert [c["metadata"]["nbgrader"]["grade_id"] for c in cells] == [
        c["grade_id"] for c in doc["checks"]
    ]
    assert nbgrader_validate(notebook) == []
    assert is_gated(module, topic)


# --- the whole library, and the bar the seeds already hold -------------------


def test_reaudit_gates_walks_a_tree_and_counts_both_outcomes(gated):
    module, topic = gated
    _, sidecar, _, _ = pre_tightening(module, topic)

    report = reaudit_gates(sidecar.parent)

    assert (report["gates"], report["holds"], report["flagged"]) == (1, 0, 1)
    assert report["results"][0].checks == "ownership.checks.json"
    assert any("passes an empty submission" in f for f in report["results"][0].failures)


def test_every_shipped_seed_gate_still_holds_the_tightened_bar():
    """Every gate on disk would be accepted by today's write path.

    A floor rather than an equality, for the reason test_gateaudit gives: the backfill
    adds gates, and a suite that fails when coverage rises punishes the tool for
    working. What stays exact is that every gate holds — none flagged, holds equal to
    gates — which is the claim the count was standing in for.
    """
    report = reaudit_gates(ROOT / "notebooks")

    assert report["gates"] >= 24
    flagged = {r.checks: list(r.failures) for r in report["results"] if r.outcome != HOLDS}
    assert flagged == {}
    assert report["holds"] == report["gates"]
