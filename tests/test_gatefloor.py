"""The coverage ratchet: coverage may rise, and it may not silently fall back.

`praxis/gatefloor.py` records one number — the coverage already reached — and fails when
the library drops below it. Everything asserted here is about that one direction, plus
the two ways the check could be switched off without anybody noticing: deleting the floor
(which must fail, not pass) and letting the README's reader-facing claim drift away from
the enforced figure.

The last two tests are the regression check itself, run against the shipped library. They
need no launch extra and no model — `measure()` folds `backfill.coverage()`, which is the
same `is_gated()` the batch that writes gates uses, so what fails here is a real drop in
gate coverage rather than a second opinion about what a gate is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxis.gatefloor import (  # noqa: E402
    CLAIM_SHAPE,
    claim,
    claim_failures,
    floor_path,
    load_floor,
    measure,
    readme_path,
    record,
    regressions,
    report,
    write_claim,
)

FLOOR = {
    "version": 1,
    "recorded": "2026-08-27",
    "gated": 9,
    "total": 20,
    "domainsGated": 2,
    "domainsTotal": 3,
    "domains": [
        {"dir": "01-alpha", "gated": 5, "total": 5},
        {"dir": "02-beta", "gated": 4, "total": 10},
        {"dir": "03-gamma", "gated": 0, "total": 5},
    ],
}


def live(**gated: int) -> dict:
    """A measurement shaped like `measure()`, with per-domain counts overridden."""
    rows = [{"dir": d["dir"], "gated": gated.get(d["dir"], d["gated"]), "total": d["total"]}
            for d in FLOOR["domains"] if d["dir"] not in gated.get("_drop", ())]
    total = sum(r["total"] for r in rows)
    count = sum(r["gated"] for r in rows)
    return {"gated": count, "total": total,
            "pct": round(100 * count / total) if total else 0,
            "domainsGated": sum(1 for r in rows if r["gated"]),
            "domainsTotal": len(rows), "domains": rows}


# --- the one direction that is a failure ------------------------------------


def test_coverage_that_has_not_moved_holds():
    assert regressions(live(), FLOOR) == ()


def test_a_rise_is_never_a_regression():
    """The floor is a floor. A suite that failed when a backfill worked would be
    punishing the tool for doing its job — the same rule test_gateaudit and test_regate
    already follow."""
    assert regressions(live(**{"02-beta": 10, "03-gamma": 5}), FLOOR) == ()


def test_a_domain_that_lost_a_gate_is_named_even_when_the_headline_holds():
    """Why the floor is per domain: five gates moving from one domain to another leaves
    the overall count flat, and the headline cannot see it. The per-domain fraction is
    the primary figure everywhere else in this program; it is the primary figure here."""
    moved = live(**{"01-alpha": 0, "03-gamma": 5})
    assert moved["gated"] == FLOOR["gated"]
    assert [f for f in regressions(moved, FLOOR) if f.startswith("01-alpha")]
    assert not [f for f in regressions(moved, FLOOR) if f.startswith("library")]


def test_an_overall_drop_is_reported_with_both_numbers():
    (failure,) = [f for f in regressions(live(**{"02-beta": 1}), FLOOR)
                  if f.startswith("library")]
    assert "6/20" in failure and "9/20" in failure


def test_a_domain_dropped_out_of_the_library_is_a_regression():
    """The only way to lose a gating domain is to delete notebooks that were gating."""
    gone = live(_drop=("01-alpha",))
    assert any("01-alpha" in f and "no longer in the library" in f
               for f in regressions(gone, FLOOR))


def test_a_new_domain_the_floor_never_saw_is_not_a_regression():
    fresh = live()
    fresh["domains"].append({"dir": "04-delta", "gated": 0, "total": 7})
    fresh["total"] += 7
    assert regressions(fresh, FLOOR) == ()


# --- the ways the check could be switched off -------------------------------


def test_no_floor_at_all_fails_rather_than_passing(tmp_path):
    """Deleting the record is the one edit that would disable this check, so it degrades
    loudly — the same direction praxis/ungated.py degrades in."""
    (failure,) = regressions(live(), load_floor(tmp_path / "absent.json"))
    assert "no coverage floor is recorded" in failure


def test_an_unreadable_floor_reads_as_no_floor_and_so_fails(tmp_path):
    corrupt = tmp_path / "coverage-floor.json"
    corrupt.write_text("{not json")
    assert regressions(live(), load_floor(corrupt)) != ()


def test_a_floor_of_the_wrong_version_is_not_believed(tmp_path):
    stale = tmp_path / "coverage-floor.json"
    stale.write_text(json.dumps({**FLOOR, "version": 2}))
    assert regressions(live(), load_floor(stale)) != ()


# --- the reader-facing claim ------------------------------------------------


def test_the_readme_claim_round_trips_through_the_floor():
    text = "intro\n\n" + CLAIM_SHAPE.format(gated=1, total=2, pct=50, domainsGated=1,
                                            domainsTotal=1) + "\n\noutro\n"
    updated = write_claim(text, FLOOR)
    assert claim(updated) == {"gated": 9, "total": 20, "pct": 45,
                              "domainsGated": 2, "domainsTotal": 3}
    assert updated.startswith("intro") and updated.endswith("outro\n")


def test_a_document_with_no_claim_fails_loudly():
    """A claim quietly deleted would leave coverage discoverable only by running a
    command again — which is the state this module exists to end."""
    with pytest.raises(ValueError):
        claim("# Praxis\n\nNo numbers here.\n")
    assert claim_failures(FLOOR, "# Praxis\n")


def test_each_disagreeing_number_is_named():
    text = CLAIM_SHAPE.format(gated=99, total=20, pct=45, domainsGated=2, domainsTotal=3)
    (failure,) = claim_failures(FLOOR, text)
    assert "gated=99" in failure and "9" in failure


def test_the_claim_is_checked_against_the_floor_not_against_live_coverage():
    """So a backfill that raises coverage never fails the README; only moving the
    ratchet without moving the sentence does, and `record()` moves both."""
    text = write_claim(CLAIM_SHAPE.format(gated=0, total=0, pct=0, domainsGated=0,
                                          domainsTotal=0), FLOOR)
    assert claim_failures(FLOOR, text) == ()
    assert report(live(**{"02-beta": 10}), FLOOR, text)["claim"] == []


# --- recording -------------------------------------------------------------


def test_record_writes_the_floor_and_the_claim_from_one_measurement(tmp_path):
    floor_file = tmp_path / "coverage-floor.json"
    readme = tmp_path / "README.md"
    readme.write_text("# x\n\n" + CLAIM_SHAPE.format(
        gated=0, total=0, pct=0, domainsGated=0, domainsTotal=0) + "\n")

    doc = record(live(), path=floor_file, readme=readme, recorded="2026-08-27")

    assert json.loads(floor_file.read_text()) == doc
    assert claim(readme.read_text()) == {"gated": 9, "total": 20, "pct": 45,
                                         "domainsGated": 2, "domainsTotal": 3}
    assert claim_failures(load_floor(floor_file), readme.read_text()) == ()


def test_record_refuses_to_lower_the_floor(tmp_path):
    """Coverage that dropped is the failure this module reports, not a new baseline."""
    floor_file = tmp_path / "coverage-floor.json"
    floor_file.write_text(json.dumps(FLOOR))
    readme = tmp_path / "README.md"
    readme.write_text(CLAIM_SHAPE.format(gated=9, total=20, pct=45, domainsGated=2,
                                         domainsTotal=3))

    with pytest.raises(ValueError, match="refusing to lower the floor"):
        record(live(**{"01-alpha": 1}), path=floor_file, readme=readme)

    assert json.loads(floor_file.read_text()) == FLOOR


# --- the shipped library ----------------------------------------------------


def test_the_shipped_library_holds_its_recorded_floor():
    """The regression check itself. Cheap and offline: a fold over the notebooks and
    their answer keys, no model and no launch extra, so it runs wherever pytest does."""
    result = report(measure(), load_floor(), readme_path().read_text())
    assert result["regressions"] == []
    assert result["floor"]["gated"] >= 117


def test_the_readme_states_the_coverage_a_reader_can_check():
    """Criterion in one line: the number a reader meets is the number the gate enforces,
    and it is not below what the library actually gates."""
    floor, stated = load_floor(), claim(readme_path().read_text())
    assert claim_failures(floor, readme_path().read_text()) == ()
    assert stated["gated"] <= measure()["gated"]


def test_the_floor_records_every_domain_the_library_has():
    recorded = {row["dir"] for row in load_floor()["domains"]}
    assert {row["dir"] for row in measure()["domains"]} <= recorded


def test_the_floor_agrees_with_the_coverage_report_the_app_serves():
    """One definition of 'gated', read at two altitudes: `backfill.is_gated()` over the
    filesystem here, the launcher's own topic rows there. tests/test_coverage.py pins the
    view-model side against the notebooks on disk; this pins the ratchet to the same fact,
    so the gate cannot hold the library to a bar the app does not report."""
    pytest.importorskip("fastapi", reason="launch extra not installed")
    from launcher.app import build_model
    from praxis.coverage import coverage_report

    served = coverage_report(build_model()["domains"])
    counted = measure()
    assert (counted["gated"], counted["total"]) == (served["gated"], served["total"])
    assert {row["dir"]: row["gated"] for row in counted["domains"]} == \
        {row["dir"]: row["gated"] for row in served["domains"]}


def test_the_floor_on_disk_is_where_the_library_is():
    assert floor_path().parent == ROOT / "notebooks"
    assert floor_path().is_file()
