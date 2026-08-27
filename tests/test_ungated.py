"""The register of notebooks left ungated on purpose.

Before this register existed, "not gated" was one number covering two different
situations: a decision somebody made and wrote down, and a notebook nobody had got to.
What is asserted here is that the distinction is real and cannot flatter the library:

  - the register is **graded against the live rows**, not against itself, so an entry
    naming a domain that does not exist, or covering nothing because everything there
    now gates, is reported as stale rather than silently believed;
  - a decision **never covers a gated notebook** — coverage is not a decision to leave
    something ungated, and a `rel` entry overtaken by a gate is a failure;
  - a corrupt or missing register degrades toward **omitted**, never toward deferred, so
    the failure direction is loud;
  - the shipped register accounts for every ungated notebook in the seed library, which
    is the property the band was measured on.

Nothing here calls a model or writes a gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis.coverage import coverage_report  # noqa: E402
from praxis.ungated import (  # noqa: E402
    deferred_rels,
    load_register,
    register_failures,
    register_path,
)

DOMAINS = [
    {"dir": "01-alpha", "name": "Alpha", "topics": [
        {"rel": "01-alpha/a.ipynb", "gated": True, "graded": True, "status": "complete"},
        {"rel": "01-alpha/b.ipynb", "gated": False, "graded": False, "status": "complete"},
    ]},
    {"dir": "02-beta", "name": "Beta", "topics": [
        {"rel": "02-beta/c.ipynb", "gated": False, "graded": False, "status": "complete"},
        {"rel": "02-beta/d.ipynb", "gated": True, "graded": False, "status": "complete"},
    ]},
]


def entry(**kwargs):
    return {"decided": "2026-08-27", "reason": "waiting on authoring time", **kwargs}


def register(*entries):
    return {"version": 1, "entries": list(entries)}


# --- what a decision covers -------------------------------------------------


def test_a_domain_entry_covers_that_domain_s_ungated_rows_and_no_others():
    covered = deferred_rels(register(entry(dir="01-alpha")), DOMAINS)
    assert covered == {"01-alpha/b.ipynb": "waiting on authoring time"}


def test_a_half_migrated_gate_is_ungated_so_a_decision_can_cover_it():
    """`02-beta/d.ipynb` has a key but no graded cells — coverage calls that ungated."""
    covered = deferred_rels(register(entry(dir="02-beta")), DOMAINS)
    assert set(covered) == {"02-beta/c.ipynb", "02-beta/d.ipynb"}


def test_a_notebook_entry_wins_over_the_domain_it_sits_in():
    covered = deferred_rels(
        register(entry(dir="02-beta"),
                 entry(rel="02-beta/c.ipynb", reason="needs a rewrite first")),
        DOMAINS)
    assert covered["02-beta/c.ipynb"] == "needs a rewrite first"
    assert covered["02-beta/d.ipynb"] == "waiting on authoring time"


def test_a_decision_never_covers_a_gated_notebook():
    covered = deferred_rels(register(entry(rel="01-alpha/a.ipynb")), DOMAINS)
    assert covered == {}


def test_an_entry_with_no_reason_covers_nothing():
    naked = {"version": 1, "entries": [{"dir": "01-alpha", "decided": "2026-08-27"}]}
    assert deferred_rels(naked, DOMAINS) == {}


# --- grading the register ---------------------------------------------------


def test_a_well_formed_register_has_no_failures():
    assert register_failures(register(entry(dir="01-alpha")), DOMAINS) == ()


@pytest.mark.parametrize("bad, wanted", [
    ({"version": 2, "entries": []}, "version"),
    ({"version": 1, "entries": {}}, "entries must be a list"),
    (register({"reason": "x", "decided": "2026-08-27"}), "exactly one"),
    (register(entry(dir="01-alpha", rel="01-alpha/b.ipynb")), "exactly one"),
    (register({"dir": "01-alpha", "decided": "2026-08-27"}), "reason"),
    (register({"dir": "01-alpha", "reason": "x"}), "decided"),
    (register({"dir": "01-alpha", "reason": "x", "decided": "27/08/2026"}), "decided"),
    (register(entry(dir="99-nope")), "no such domain"),
    (register(entry(rel="01-alpha/nope.ipynb")), "no such notebook"),
])
def test_a_malformed_entry_is_named_with_its_problem(bad, wanted):
    failures = register_failures(bad, DOMAINS)
    assert failures, bad
    assert any(wanted in failure for failure in failures), failures


def test_a_decision_overtaken_by_a_gate_is_stale_not_silently_ignored():
    """The point of the register is that it stays honest as the backfill proceeds."""
    failures = register_failures(register(entry(rel="01-alpha/a.ipynb")), DOMAINS)
    assert any("stale" in failure for failure in failures), failures


def test_a_domain_entry_covering_nothing_is_stale():
    gated = [{"dir": "01-alpha", "topics": [
        {"rel": "01-alpha/a.ipynb", "gated": True, "graded": True}]}]
    failures = register_failures(register(entry(dir="01-alpha")), gated)
    assert any("stale" in failure for failure in failures), failures


def test_the_same_decision_twice_is_a_failure():
    twice = register(entry(dir="01-alpha"), entry(dir="01-alpha"))
    assert any("twice" in failure for failure in register_failures(twice, DOMAINS))


# --- loading ----------------------------------------------------------------


def test_a_missing_register_reads_as_no_decisions(tmp_path):
    assert load_register(tmp_path / "nothing.json") == {"version": 1, "entries": []}


def test_a_corrupt_register_raises_rather_than_reading_as_empty(tmp_path):
    path = tmp_path / "ungated.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_register(path)
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_register(path)


def test_a_corrupt_register_degrades_toward_omitted_not_deferred(tmp_path, monkeypatch):
    """The failure direction matters: a broken record must not hide an oversight."""
    path = tmp_path / "ungated.json"
    path.write_text("{not json")
    monkeypatch.setattr("praxis.ungated.register_path", lambda: path)
    report = coverage_report(DOMAINS)
    assert report["deferred"] == 0
    assert report["omitted"] == 3


# --- the report ------------------------------------------------------------


def test_coverage_splits_the_complement_into_decided_and_unaccounted_for():
    covered = deferred_rels(register(entry(dir="01-alpha")), DOMAINS)
    report = coverage_report(DOMAINS, covered)
    assert (report["gated"], report["deferred"], report["omitted"]) == (1, 1, 2)
    assert report["gated"] + report["deferred"] + report["omitted"] == report["total"]
    alpha, beta = report["domains"]
    assert (alpha["gated"], alpha["deferred"], alpha["omitted"]) == (1, 1, 0)
    assert (beta["gated"], beta["deferred"], beta["omitted"]) == (0, 0, 2)


def test_no_decisions_means_every_ungated_notebook_is_unaccounted_for():
    report = coverage_report(DOMAINS, {})
    assert report["deferred"] == 0 and report["omitted"] == 3


# --- the shipped library ---------------------------------------------------


def test_the_shipped_register_is_well_formed_and_accounts_for_every_gap():
    """A floor, not a count: the backfill's job is to shrink the deferred half.

    What must stay true is the accounting — every ungated seed notebook is either
    covered by a dated decision or shows up as unaccounted for, and there are none of
    the latter.
    """
    pytest.importorskip("fastapi", reason="launch extra not installed")
    from launcher.app import build_model

    domains = build_model()["domains"]
    shipped = load_register(register_path())
    assert register_failures(shipped, domains) == ()

    report = coverage_report(domains)
    assert report["omitted"] == 0, "an ungated notebook with no decision behind it"
    assert report["gated"] + report["deferred"] == report["total"]
    assert report["gated"] >= 117
