"""Gated coverage: how much of the library really gates, per domain and overall.

The report is a fold over the launcher's own topic rows, so what is asserted here is
that the fold cannot flatter the library. Three properties carry that:

  - a row counts only when **both** halves of the gate are on disk — the answer key and
    the nbgrader graded cells — so a half-migrated notebook is reported as ungated;
  - the overall fraction is the sum of the per-domain ones, so the headline and the
    breakdown are one number read two ways;
  - run against the shipped library, the report agrees with an independent scan of the
    notebooks on disk. That is the anti-fabrication test: no count in here is stored,
    and none of it is a placeholder — it is 24/245 today because 24 notebooks on disk
    carry a gate.

The fixture library is built the way `tests/test_backfill.py` builds one, through the
real constructor with an injected fake client, so the gates it counts are gates
`nbgrader validate` accepted. Nothing here calls a model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import save_subject, subject_from_dict  # noqa: E402
from praxis.coverage import coverage_report, domain_coverage, is_gated  # noqa: E402

LIBRARY = {
    "title": "Embedded Rust",
    "blurb": "Drive real hardware from Rust.",
    "modules": [
        {
            "title": "Foundations",
            "blurb": "The language guarantees that matter on a microcontroller.",
            "topics": [
                {"title": "Ownership and Borrowing", "slug": "ownership", "runnable": True},
                {"title": "Traits and Generics", "slug": "traits", "runnable": True},
                {"title": "Timers", "slug": "timers", "runnable": True},
                {"title": "Wiring a Dev Board", "slug": "wiring", "runnable": False,
                 "note": "needs hardware"},
            ],
        },
        {
            "title": "Peripherals",
            "blurb": "Talking to the pins.",
            "topics": [
                {"title": "GPIO", "slug": "gpio", "runnable": True},
                {"title": "SPI", "slug": "spi", "runnable": True},
            ],
        },
    ],
}


def row(rel: str, *, gated: bool = False, graded: bool = False,
        status: str = "complete") -> dict:
    """One library row, as `launcher.app._gated()` folds it."""
    return {"rel": rel, "title": rel, "status": status, "gated": gated, "graded": graded}


# --- the arithmetic ---------------------------------------------------------


def test_a_row_gates_only_when_both_halves_are_on_disk():
    """A sidecar with no graded cells is a half-migrated gate, not coverage."""
    assert is_gated(row("a", gated=True, graded=True))
    assert not is_gated(row("b", gated=True))            # key, but no cells released
    assert not is_gated(row("c", graded=True))           # cells, but nothing to grade by
    assert not is_gated(row("d"))


def test_the_overall_fraction_is_the_sum_of_the_per_domain_ones():
    """X/N per domain is the primary figure; X/total is what those add up to."""
    domains = [
        {"dir": "01-a", "name": "A", "title": "Alpha", "topics": [
            row("01-a/1", gated=True, graded=True),
            row("01-a/2", gated=True, graded=True),
            row("01-a/3"),
            row("01-a/4", status="scaffold"),
        ]},
        {"dir": "02-b", "name": "B", "title": "Beta", "topics": [
            row("02-b/1", gated=True),                   # half migrated: does not count
            row("02-b/2"),
        ]},
        {"dir": "03-c", "name": "C", "title": "Gamma", "topics": []},
    ]

    report = coverage_report(domains)

    assert [(d["name"], d["gated"], d["total"], d["pct"]) for d in report["domains"]] == [
        ("A", 2, 4, 50), ("B", 0, 2, 0), ("C", 0, 0, 0)]
    assert (report["gated"], report["total"], report["pct"]) == (2, 6, 33)
    assert report["complete"] == 5                       # one scaffold is not complete
    # Breadth: two of the three domains have no gate at all, which an overall 2/6 hides.
    assert (report["domainsGated"], report["domainsTotal"]) == (1, 3)


def test_a_domain_with_no_notebooks_is_a_zero_not_a_divide_by_zero():
    assert domain_coverage({"dir": "x", "title": "X"}) == {
        "dir": "x", "name": "X", "title": "X",
        "gated": 0, "total": 0, "complete": 0,
        "deferred": 0, "omitted": 0, "pct": 0}


# --- the same arithmetic over a real library on disk ------------------------


@pytest.fixture
def library(monkeypatch, tmp_path):
    """Two domains with a known gated subset: Foundations 1/4, Peripherals 0/2.

    Built through the real constructor, so `ownership`'s gate is one `nbgrader validate`
    accepted — and the seed domains are patched out so the count is the fixture's.
    """
    pytest.importorskip("fastapi", reason="launch extra not installed")
    monkeypatch.setenv("PRAXIS_SUBJECTS_DIR", str(tmp_path / "notebooks" / "subjects"))

    import launcher.app as launcher_app
    from praxis.construct import construct_topic
    from scaffold_notebooks import scaffold_subject
    from test_construct import FakeClient, good_cells
    from test_construct import reply as cell_reply

    subject = subject_from_dict(LIBRARY, goal="drive a microcontroller from Rust")
    save_subject(subject)
    scaffold_subject(subject)
    foundations, peripherals = subject.modules
    construct_topic(foundations, foundations.topics[0],
                    client=FakeClient(cell_reply(good_cells())))
    for module, index in [(foundations, 1), (foundations, 2),
                          (peripherals, 0), (peripherals, 1)]:
        construct_topic(module, module.topics[index],
                        client=FakeClient(cell_reply(good_cells())), checks=False)
    monkeypatch.setattr(launcher_app, "DOMAINS", [])     # only the fixture's domains
    return launcher_app, subject


def test_the_report_counts_the_gates_a_fixture_library_really_has(library):
    launcher_app, _ = library

    report = coverage_report(launcher_app.build_model()["domains"])

    # Per domain first — the figure a breadth-first backfill is measured on.
    assert [(d["name"], d["gated"], d["total"]) for d in report["domains"]] == [
        ("Foundations", 1, 4), ("Peripherals", 0, 2)]
    assert (report["gated"], report["total"]) == (1, 6)
    assert (report["domainsGated"], report["domainsTotal"]) == (1, 2)


def test_gating_one_more_topic_moves_the_number_with_no_second_scan(library):
    """What makes a backfill batch visible: the report is the library, re-read."""
    launcher_app, subject = library
    from praxis.backfill import backfill_domain
    from test_construct import FakeClient

    before = coverage_report(launcher_app.build_model()["domains"])
    backfill_domain(subject.modules[1], subject=subject, client=FakeClient(), limit=1)
    after = coverage_report(launcher_app.build_model()["domains"])

    assert (before["gated"], before["total"]) == (1, 6)
    assert (after["gated"], after["total"]) == (2, 6)
    assert [(d["name"], d["gated"]) for d in after["domains"]] == [
        ("Foundations", 1), ("Peripherals", 1)]        # breadth, not depth


def test_the_shipped_library_report_agrees_with_the_notebooks_on_disk():
    """The anti-fabrication assertion: the count is derived, never asserted.

    Counted here a second, deliberately independent way — straight off the files — so
    the report cannot report coverage the library does not have. It stays true as the
    backfill lands: it pins the *agreement*, not today's 24.
    """
    pytest.importorskip("fastapi", reason="launch extra not installed")
    from launcher.app import NOTEBOOKS_DIR, build_model
    from praxis.checks import CHECKS_EXTENSION, checks_path

    def carries_a_gate(path: Path) -> bool:
        nb = json.loads(path.read_text())
        cells = [c for c in nb.get("cells", [])
                 if c.get("metadata", {}).get("praxis", {}).get("extension")
                 == CHECKS_EXTENSION]
        doc = checks_path(path)
        return bool(cells) and doc.is_file() and bool(json.loads(doc.read_text())["checks"])

    on_disk = [p for p in sorted(NOTEBOOKS_DIR.rglob("*.ipynb"))
               if ".ipynb_checkpoints" not in p.parts]
    report = coverage_report(build_model()["domains"])

    assert report["total"] == len(on_disk) >= 245
    assert report["gated"] == sum(carries_a_gate(p) for p in on_disk)
    assert report["gated"] == sum(d["gated"] for d in report["domains"])
