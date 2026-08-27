#!/usr/bin/env python3
"""The coverage ratchet: gate coverage may rise, and it may not silently fall back.

`praxis/coverage.py` says how much of the library gates *right now* and stores nothing,
on purpose. That is the right rule for a report and the wrong one for a regression check:
a number nobody records is a number nobody notices moving, which is exactly how the
library sat at 24/245 while the machinery to fix it was already merged. So this module
records one thing and only one thing — the coverage that has already been reached — and
fails when the library falls below it.

The recorded number is **not** coverage and is never read as coverage. It is a floor, and
the distinction is the whole design:

  - coverage is always **measured** (`measure()`), never loaded;
  - the floor is always **loaded** (`load_floor()`), never measured;
  - `regressions()` compares the two and reports only the direction that matters. A rise
    is not a failure — a suite that failed when coverage rose would punish the backfill
    for working, the same reason `gateaudit` and `regate` pin floors rather than counts.

**It is cheap and offline.** `measure()` folds `backfill.coverage()`, which is
`backfill.is_gated()` over the notebooks on disk — an answer key beside a notebook that
carries nbgrader cells. No model, no network, and no launch extra, so the check runs in
the same bare environment `pytest tests/` does rather than skipping itself there. That it
agrees with the view-model report `/api/library` serves is pinned by
`tests/test_coverage.py`, so there is still exactly one definition of "gated".

**The floor is also what a reader meets.** `README.md` carries the coverage claim in
prose, and `claim()` reads the numbers back out of that sentence: the reader-facing figure
and the enforced floor are checked against each other, so the README cannot drift into
describing a library that no longer exists (it described a 24/245 one for a fortnight
after the backfill ran). `record()` moves both together — that is the only supported way
to raise the ratchet, precisely so they cannot be moved apart.

A missing or unreadable floor is a **failure**, not an absence. Deleting the record is the
one edit that would switch this check off, so it degrades loudly rather than quietly, the
same direction `praxis/ungated.py` degrades in.

CLI:
    python3 -m praxis.gatefloor            live vs the floor; exit 1 if it dropped
    python3 -m praxis.gatefloor --json     the same comparison, machine-readable
    python3 -m praxis.gatefloor --record   raise the ratchet: rewrite the floor + README
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FLOOR_NAME = "coverage-floor.json"

EMPTY: dict = {"version": 1, "recorded": "", "gated": 0, "total": 0, "domains": []}

#: The README's coverage sentence, as a reader meets it and as this module reads it.
#: Deliberately strict: an edit that reshapes the claim fails the gate naming the
#: sentence, rather than passing because a loose pattern still matched something.
CLAIM = re.compile(
    r"\*\*Gate coverage:\s+(?P<gated>\d+)\s+of\s+the\s+(?P<total>\d+)\s+seed\s+tutorials"
    r"\s+gate\s+progression\s+\((?P<pct>\d+)%\),\s+across\s+(?P<domainsGated>\d+)\s+of"
    r"\s+(?P<domainsTotal>\d+)\s+domains\.\*\*")

CLAIM_SHAPE = ("**Gate coverage: {gated} of the {total} seed tutorials gate progression "
               "({pct}%), across {domainsGated} of {domainsTotal} domains.**")


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def floor_path() -> Path:
    """`notebooks/coverage-floor.json` — beside the library whose coverage it floors.

    Next to `notebooks/ungated.json` and for the same reason: it is a fact about the seed
    library that ships with the app, so it is tracked with it rather than written to a
    storage backend where a user's own subjects live.
    """
    import curriculum  # noqa: PLC0415  (a path, not an import-time dependency)

    return curriculum.NOTEBOOKS_DIR / FLOOR_NAME


def readme_path() -> Path:
    """The one reader-facing document the floor is kept in step with."""
    return ROOT / "README.md"


def measure(counts: Sequence[tuple] | None = None) -> dict:
    """Coverage as it is on disk right now — the same fact `praxis.coverage` reports.

    `counts` is `backfill.coverage()`'s rows (`domain, gated, complete, total`), taken
    live when not supplied. Folding that function rather than walking the notebooks again
    is the point: `backfill.is_gated()` decides what a gate is, here as in the batch that
    writes them, so the ratchet cannot hold the library to a bar the backfill does not
    recognise.
    """
    if counts is None:
        from praxis.backfill import coverage  # noqa: PLC0415

        counts = coverage()
    domains = [{"dir": domain.dir, "gated": gated, "total": total}
               for domain, gated, _complete, total in counts]
    gated = sum(d["gated"] for d in domains)
    total = sum(d["total"] for d in domains)
    return {
        "gated": gated,
        "total": total,
        "pct": _pct(gated, total),
        "domainsGated": sum(1 for d in domains if d["gated"]),
        "domainsTotal": len(domains),
        "domains": domains,
    }


def load_floor(path: str | Path | None = None) -> dict:
    """The recorded floor, or an empty one that fails every comparison.

    Unlike a register of decisions, a missing floor is not a legitimate state: the record
    is the check, so "no file" and "not valid JSON" both have to be reported rather than
    read as "nothing to hold the library to". `regressions()` turns the empty floor into
    a sentence saying so.
    """
    path = Path(path) if path is not None else floor_path()
    if not path.is_file():
        return dict(EMPTY)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return dict(EMPTY)
    if not isinstance(data, dict) or data.get("version") != 1:
        return dict(EMPTY)
    return data


def _by_dir(floor: dict) -> dict[str, dict]:
    return {str(d.get("dir")): d for d in (floor.get("domains") or [])
            if isinstance(d, dict)}


def regressions(live: dict, floor: dict) -> tuple[str, ...]:
    """Every way coverage has fallen below what was already reached, in sentences.

    Per domain first, because the per-domain fraction is the primary figure everywhere
    else in this program: a batch that gates five notebooks in one domain while five stop
    gating in another leaves the overall number flat, and that is a regression the
    headline cannot see.

    Only downward movement is reported. A domain the floor does not know about is new and
    therefore fine; a domain in the floor that the library no longer has is not, because
    the only way to lose one is to delete notebooks that were gating.
    """
    if not (floor.get("domains") or floor.get("total")):
        return (f"no coverage floor is recorded ({floor_path()}) — "
                "run `python3 -m praxis.gatefloor --record`",)

    failures: list[str] = []
    recorded = _by_dir(floor)
    for row in live.get("domains") or []:
        was = recorded.get(str(row["dir"]))
        if was is not None and row["gated"] < int(was.get("gated", 0)):
            failures.append(f"{row['dir']}: {row['gated']}/{row['total']} gated, "
                            f"below the recorded floor of {was.get('gated')}")
    present = {str(row["dir"]) for row in (live.get("domains") or [])}
    for dir_, was in recorded.items():
        if dir_ not in present and int(was.get("gated", 0)):
            failures.append(f"{dir_}: recorded at {was.get('gated')} gated, "
                            "but the domain is no longer in the library")
    if live.get("gated", 0) < int(floor.get("gated", 0)):
        failures.append(f"library: {live.get('gated')}/{live.get('total')} gated, "
                        f"below the recorded floor of {floor.get('gated')}/"
                        f"{floor.get('total')}")
    return tuple(failures)


def claim(text: str) -> dict:
    """The coverage figures the README states, read back out of the prose.

    Raises when the sentence is gone. That is the point of reading it at all: a claim
    quietly deleted would leave the number discoverable only by running a command again,
    which is the state this whole story exists to end.
    """
    match = CLAIM.search(text)
    if match is None:
        raise ValueError(
            f"{readme_path().name} states no gate-coverage claim — it must carry the "
            f"sentence {CLAIM_SHAPE.format(**dict.fromkeys(CLAIM.groupindex, 'N'))!r}")
    return {key: int(value) for key, value in match.groupdict().items()}


def claim_failures(floor: dict, text: str) -> tuple[str, ...]:
    """Where the README's claim and the recorded floor disagree.

    Checked against the floor rather than against live coverage, so a backfill that
    raises coverage never fails this: the README goes stale only when somebody moves the
    ratchet without moving the sentence, and `record()` moves both.
    """
    try:
        stated = claim(text)
    except ValueError as exc:
        return (str(exc),)
    expected = {"gated": int(floor.get("gated", 0)), "total": int(floor.get("total", 0)),
                "pct": _pct(int(floor.get("gated", 0)), int(floor.get("total", 0))),
                "domainsGated": int(floor.get("domainsGated", 0)),
                "domainsTotal": int(floor.get("domainsTotal", 0))}
    return tuple(f"README claims {key}={stated[key]}, the floor records {value}"
                 for key, value in expected.items() if stated[key] != value)


def write_claim(text: str, floor: dict) -> str:
    """The README with its coverage sentence set to the floor's numbers."""
    claim(text)  # fail loudly if there is nothing to replace
    return CLAIM.sub(
        lambda _: CLAIM_SHAPE.format(
            gated=floor.get("gated", 0), total=floor.get("total", 0),
            pct=_pct(int(floor.get("gated", 0)), int(floor.get("total", 0))),
            domainsGated=floor.get("domainsGated", 0),
            domainsTotal=floor.get("domainsTotal", 0)),
        text, count=1)


def record(live: dict | None = None, *, path: str | Path | None = None,
           readme: str | Path | None = None, recorded: str | None = None) -> dict:
    """Raise the ratchet: write the floor and the README's claim from one measurement.

    Both, always, from the same numbers — the two artifacts exist to be checked against
    each other and there is no supported way to move one without the other. Refuses to
    lower the floor: coverage that dropped is the failure this module reports, not a new
    baseline to settle for.
    """
    live = measure() if live is None else live
    floor = load_floor(path)
    dropped = regressions(live, floor)
    if dropped and floor.get("total"):
        raise ValueError("refusing to lower the floor: " + "; ".join(dropped))
    doc = {"version": 1,
           "recorded": recorded or date.today().isoformat(),
           "gated": live["gated"], "total": live["total"],
           "domainsGated": live["domainsGated"], "domainsTotal": live["domainsTotal"],
           "domains": live["domains"]}
    target = Path(path) if path is not None else floor_path()
    target.write_text(json.dumps(doc, indent=2) + "\n")
    readme_file = Path(readme) if readme is not None else readme_path()
    readme_file.write_text(write_claim(readme_file.read_text(), doc))
    return doc


def report(live: dict | None = None, floor: dict | None = None,
           text: str | None = None) -> dict:
    """The whole check in one value: what is live, what is recorded, what is wrong."""
    live = measure() if live is None else live
    floor = load_floor() if floor is None else floor
    text = readme_path().read_text() if text is None else text
    return {"live": live, "floor": floor,
            "regressions": list(regressions(live, floor)),
            "claim": list(claim_failures(floor, text))}


def render(result: dict) -> str:
    live, floor = result["live"], result["floor"]
    lines = [f"live  {live['gated']}/{live['total']} gated ({live['pct']}%), "
             f"in {live['domainsGated']} of {live['domainsTotal']} domains",
             f"floor {floor.get('gated', 0)}/{floor.get('total', 0)} gated, "
             f"recorded {floor.get('recorded') or 'never'}"]
    failures = result["regressions"] + result["claim"]
    lines.append("")
    lines.append("coverage HOLDS" if not failures
                 else f"coverage REGRESSED — {len(failures)} problem(s)")
    lines.extend(f"  - {failure}" for failure in failures)
    return "\n".join(lines)


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    live = measure()
    if "--record" in argv:
        doc = record(live)
        print(f"recorded {doc['gated']}/{doc['total']} gated in "
              f"{doc['domainsGated']} of {doc['domainsTotal']} domains "
              f"({doc['recorded']}) — {floor_path()} and {readme_path().name}")
        return 0
    result = report(live)
    print(json.dumps(result, indent=2) if "--json" in argv else render(result))
    return 1 if result["regressions"] or result["claim"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
