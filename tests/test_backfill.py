"""The gating backfill: a ✅-but-ungated domain in, a gated one out.

The backfill writes no gate of its own — it selects targets and hands them to the
shipped batch loop — so what is asserted here is the selection and the two properties
that make an unattended run safe: an already-gated notebook is skipped rather than
rewritten, and a notebook that is not yet ✅ is left for construction rather than
force-gated. The anti-fabrication bar is asserted where it bites: a set whose reference
solution does not pass its own test leaves the notebook ungated, and a gate that is
written passes `nbgrader validate`.

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
from nbstatus import notebook_status  # noqa: E402
from praxis import construct  # noqa: E402
from praxis.backfill import (  # noqa: E402
    backfill_domain,
    backfill_targets,
    domain_targets,
    is_gated,
)
from praxis.checks import (  # noqa: E402
    GATED_SECTIONS,
    checks_path,
    checkset_failures,
    graded_cells,
    load_checks,
    nbgrader_validate,
)
from praxis.construct import construct_topic  # noqa: E402
from scaffold_notebooks import scaffold_subject  # noqa: E402
from test_checks import code, good_checks  # noqa: E402
from test_checks import reply as checks_reply  # noqa: E402
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
                {"title": "Traits and Generics", "slug": "traits", "runnable": True},
                {"title": "Wiring a Dev Board", "slug": "wiring", "runnable": False,
                 "note": "needs hardware"},
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def subjects_root(monkeypatch, tmp_path) -> Path:
    """Every write lands in a temp dir — never the developer's notebooks/."""
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))
    return tmp_path / "notebooks" / "subjects"


@pytest.fixture
def domain():
    """A module in exactly the state the seed library is in: mixed.

    `ownership` is ✅ and gated, `traits` is ✅ and ungated (the backlog this band
    exists for), `wiring` is still a scaffold.
    """
    subject = subject_from_dict(CURRICULUM, goal="drive a microcontroller from Rust")
    save_subject(subject)
    scaffold_subject(subject)
    module = subject.modules[0]
    construct_topic(module, module.topics[0], client=FakeClient(cell_reply(good_cells())))
    construct_topic(module, module.topics[1], client=FakeClient(cell_reply(good_cells())),
                    checks=False)
    return module, subject


def slugs(results) -> list[str]:
    return [r.slug for r in results]


def snapshot(module) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(topic_path(module, module.topics[0]).parent
                                              .rglob("*")) if p.is_file()}


# --- what a backfill selects ------------------------------------------------


def test_every_notebook_on_disk_is_a_candidate(domain):
    module, subject = domain

    found = domain_targets(module, subject=subject)

    assert [t.slug for _, t, _ in found] == ["ownership", "traits", "wiring"]
    assert {s for _, _, s in found} == {subject}


def test_only_the_ungated_complete_notebooks_are_targets(domain):
    module, subject = domain

    targets = backfill_targets(module, subject=subject)

    # ownership is already gated; wiring is a scaffold and belongs to construction.
    assert [t.slug for _, t, _ in targets] == ["traits"]
    assert is_gated(module, module.topics[0])
    assert not is_gated(module, module.topics[1])


def test_a_sidecar_without_graded_cells_does_not_count_as_gated(domain):
    """`needs_checks()` re-expressed against the schema: the cells are the gate."""
    module, _ = domain
    path = topic_path(module, module.topics[0])
    nb = json.loads(path.read_text())
    nb["cells"] = [c for c in nb["cells"] if c not in graded_cells(nb)]
    path.write_text(json.dumps(nb, indent=1) + "\n")

    assert checks_path(path).is_file()          # the answer key is still there...
    assert not is_gated(module, module.topics[0])  # ...but the learner meets no gate


# --- what a backfill writes -------------------------------------------------


def test_an_ungated_notebook_gains_a_validating_nbgrader_gate(domain):
    module, subject = domain
    client = FakeClient()
    topic = module.topics[1]

    results = backfill_domain(module, subject=subject, client=client)

    assert slugs(results) == ["traits"]
    (result,) = results
    assert result.status == "skipped"            # the prose was already complete...
    assert result.checks.status == "generated"   # ...the gate is what this wrote
    assert client.calls == []                    # no notebook was reconstructed
    assert len(client.check_calls) == 1

    path = topic_path(module, topic)
    doc = load_checks(checks_path(path))
    assert checkset_failures(doc) == []
    cells = graded_cells(json.loads(path.read_text()))
    assert len(cells) == len(doc["checks"]) == len(GATED_SECTIONS) + 1
    assert [c["metadata"]["nbgrader"]["grade_id"] for c in cells] == [
        c["grade_id"] for c in doc["checks"]
    ]
    assert all(c["metadata"]["nbgrader"]["grade"] for c in cells)
    assert nbgrader_validate(path) == []
    assert is_gated(module, topic)
    # The released notebook carries the questions, never the answers.
    assert "return list(values)" not in path.read_text()


def test_an_already_gated_notebook_is_skipped_not_rewritten(domain):
    module, subject = domain
    gated = topic_path(module, module.topics[0])
    before = (gated.read_bytes(), checks_path(gated).read_bytes())

    backfill_domain(module, subject=subject, client=FakeClient())

    assert (gated.read_bytes(), checks_path(gated).read_bytes()) == before


def test_a_notebook_that_is_not_complete_is_left_for_construction(domain):
    module, subject = domain
    scaffold = topic_path(module, module.topics[2])
    before = scaffold.read_bytes()
    client = FakeClient()

    results = backfill_domain(module, subject=subject, client=client)

    assert "wiring" not in slugs(results)
    assert client.calls == []                    # nothing tried to construct it
    assert scaffold.read_bytes() == before
    assert notebook_status(scaffold)[0] == "scaffold"
    assert not checks_path(scaffold).is_file()


def test_a_rerun_gates_nothing_and_rewrites_nothing(domain):
    module, subject = domain
    backfill_domain(module, subject=subject, client=FakeClient())
    before = snapshot(module)

    client = FakeClient()
    results = backfill_domain(module, subject=subject, client=client)

    assert results == []                         # nothing left to select
    assert client.calls == [] and client.check_calls == []
    assert snapshot(module) == before


def test_a_stored_set_with_no_graded_cells_is_repaired_without_the_model(domain):
    """The half-migrated state converges instead of being selected for ever."""
    module, subject = domain
    path = topic_path(module, module.topics[0])
    nb = json.loads(path.read_text())
    stale = graded_cells(nb)
    nb["cells"] = [c for c in nb["cells"] if c not in stale]
    path.write_text(json.dumps(nb, indent=1) + "\n")
    key = checks_path(path).read_bytes()
    client = FakeClient()

    (result,) = backfill_domain(module, subject=subject, client=client, limit=1)

    assert result.slug == "ownership"
    assert client.check_calls == []              # the stored answer key was reused
    assert checks_path(path).read_bytes() == key
    assert is_gated(module, module.topics[0])
    assert nbgrader_validate(path) == []


def test_limit_is_the_depth_knob_a_breadth_first_pass_turns_down(domain):
    module, subject = domain

    results = backfill_domain(module, subject=subject, client=FakeClient(), limit=0)

    assert results == []
    assert not is_gated(module, module.topics[1])


# --- anti-fabrication -------------------------------------------------------


def test_a_gate_whose_solution_fails_its_own_test_is_not_written(domain):
    module, subject = domain
    topic = module.topics[1]
    path = topic_path(module, topic)
    before = path.read_bytes()
    # A reference solution that does not satisfy the check's own assertions.
    bad = [c for c in good_checks() if c["kind"] != "code"] + [
        dict(code(GATED_SECTIONS[3]), solution="def owned(values):\n    return values")
    ]
    client = FakeClient(checks=checks_reply(bad))

    (result,) = backfill_domain(module, subject=subject, client=client, attempts=1)

    assert result.checks.status == "failed" and not result.checks_ok
    assert any("reference solution does not pass" in f for f in result.checks.failures)
    assert not checks_path(path).is_file()
    assert path.read_bytes() == before           # no gate, and no half-written notebook
    assert not is_gated(module, topic)


def test_a_domain_with_nothing_to_do_needs_no_model_at_all(domain, monkeypatch):
    """The `_LazyClient` contract, kept: a finished domain costs no key."""
    module, subject = domain
    backfill_domain(module, subject=subject, client=FakeClient())

    def no_client(*args, **kwargs):
        raise AssertionError("a finished backfill must not resolve a model client")

    monkeypatch.setattr(construct, "LLMClient", no_client)

    assert backfill_domain(module, subject=subject) == []
