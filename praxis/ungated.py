#!/usr/bin/env python3
"""Which ungated notebooks are ungated *on purpose* — and why.

`praxis/coverage.py` counts what gates. Until now the complement of that count was a
single undifferentiated number: 128 notebooks with no gate, with nothing on disk to say
whether that was a decision or an oversight. This module is that distinction, and it is
deliberately the smallest thing that can carry it — a tracked register of entries, each
naming what it covers, why, and when the call was made.

**It is a record, not a rule.** Nothing here excludes a notebook from
`backfill.backfill_targets()`: a deferred notebook is still work, and a register that
quietly shrank the batch would turn "we decided to wait" into "we forgot", which is the
very confusion it exists to remove. The only thing it changes is what the report says
about the notebooks that have no gate yet.

**One entry, one reason, one date.** An entry covers either a whole domain (`dir`) or a
single notebook (`rel`), and a `dir` entry covers exactly that domain's *currently
ungated* rows — so gating one of them shrinks what the entry covers instead of
invalidating it. That is what lets the register survive a partial batch without anybody
editing it, and it is why a `rel` entry naming an already-gated notebook is a *failure*:
that decision has been overtaken by events and the line is now noise.

Like every other document in this repo, it is **graded before it is trusted**:
`register_failures()` is the machine-readable half of the format, and it is checked
against the live library rather than against itself — an entry naming a domain that does
not exist, or covering nothing, is stale and says so. `python3 -m praxis.ungated` prints
the register and exits non-zero when it fails.

The register is folded onto the same view-model rows `coverage.py` already folds over
(`launcher.app.build_model()`), for the reason that module gives for never scanning: a
second pass over the notebooks would be a second definition of "gated" and the two would
drift.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REGISTER_NAME = "ungated.json"

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EMPTY: dict = {"version": 1, "entries": []}


def register_path() -> Path:
    """`notebooks/ungated.json` — beside the library it describes, and tracked.

    The seed library ships with the app and is never written to by a learner, so its
    register belongs with it rather than on the storage backend where a user's own
    subjects live.
    """
    import curriculum  # noqa: PLC0415  (a path, not an import-time dependency)

    return curriculum.NOTEBOOKS_DIR / REGISTER_NAME


def load_register(path: str | Path | None = None) -> dict:
    """The register on disk, or an empty one when there is none.

    A missing file is a library with no deferrals, which is a legitimate state. A file
    that is present but unreadable is not: that is a corrupt record, and reporting it as
    "no deferrals" would silently turn every deferred notebook back into an omission.
    """
    path = Path(path) if path is not None else register_path()
    if not path.is_file():
        return dict(EMPTY)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold an object")
    return data


def _rows(domains: Sequence[dict]) -> dict[str, dict]:
    return {row["rel"]: row for domain in domains for row in (domain.get("topics") or [])}


def register_failures(register: dict, domains: Sequence[dict]) -> tuple[str, ...]:
    """Everything wrong with this register, in the register's own vocabulary.

    Checked against `domains` — the live library rows — because a register that only
    agreed with itself would keep claiming decisions about notebooks that have since
    been gated, renamed or removed.
    """
    failures: list[str] = []
    if register.get("version") != 1:
        failures.append(f"version must be 1, got {register.get('version')!r}")
    entries = register.get("entries")
    if not isinstance(entries, list):
        return tuple(failures + ["entries must be a list"])

    rows = _rows(domains)
    dirs = {domain.get("dir") for domain in domains}
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        where = f"entry {index}"
        if not isinstance(entry, dict):
            failures.append(f"{where}: must be an object")
            continue
        keys = [key for key in ("dir", "rel") if entry.get(key)]
        if len(keys) != 1:
            failures.append(f"{where}: needs exactly one of 'dir' or 'rel'")
            continue
        kind, target = keys[0], str(entry[keys[0]])
        where = f"entry {index} ({kind} {target!r})"
        if (kind, target) in seen:
            failures.append(f"{where}: listed twice")
        seen.add((kind, target))
        if not str(entry.get("reason") or "").strip():
            failures.append(f"{where}: needs a non-empty 'reason'")
        if not DATE.match(str(entry.get("decided") or "")):
            failures.append(f"{where}: 'decided' must be a YYYY-MM-DD date")
        if kind == "rel":
            row = rows.get(target)
            if row is None:
                failures.append(f"{where}: no such notebook in the library")
            elif row.get("gated") and row.get("graded"):
                failures.append(f"{where}: already gated — the decision is stale")
        elif target not in dirs:
            failures.append(f"{where}: no such domain in the library")
        elif not _ungated_in(target, domains):
            failures.append(f"{where}: every notebook there is gated — the decision is stale")
    return tuple(failures)


def _ungated_in(dir_: str, domains: Sequence[dict]) -> list[str]:
    for domain in domains:
        if domain.get("dir") != dir_:
            continue
        return [row["rel"] for row in (domain.get("topics") or [])
                if not (row.get("gated") and row.get("graded"))]
    return []


def deferred_rels(register: dict, domains: Sequence[dict]) -> dict[str, str]:
    """rel -> reason, for every ungated notebook a decision covers.

    A `dir` entry covers that domain's ungated rows; a `rel` entry covers one notebook
    and wins over a domain entry, so a single notebook can carry its own reason inside a
    domain that carries a general one. A notebook that already gates is never covered:
    coverage is not a decision to leave something ungated.
    """
    covered: dict[str, str] = {}
    rows = _rows(domains)
    for entry in register.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason") or "").strip()
        if not reason:
            continue
        if entry.get("dir"):
            for rel in _ungated_in(str(entry["dir"]), domains):
                covered.setdefault(rel, reason)
    for entry in register.get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("rel"):
            continue
        rel = str(entry["rel"])
        row = rows.get(rel)
        reason = str(entry.get("reason") or "").strip()
        if reason and row is not None and not (row.get("gated") and row.get("graded")):
            covered[rel] = reason
    return covered


# --- CLI --------------------------------------------------------------------


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    from launcher.app import build_model  # noqa: PLC0415  (the adapter, not a dependency)
    from praxis.progress import DEFAULT_LEARNER  # noqa: PLC0415

    domains = build_model(DEFAULT_LEARNER)["domains"]
    register = load_register()
    failures = register_failures(register, domains)
    covered = deferred_rels(register, domains)

    for entry in register.get("entries") or []:
        target = entry.get("dir") or entry.get("rel")
        count = len(_ungated_in(str(entry["dir"]), domains)) if entry.get("dir") else 1
        print(f"{str(target):<44} {count:>4} ungated  {entry.get('decided', '?')}")
        print(f"    {entry.get('reason', '')}")
    total = sum(len(domain.get("topics") or []) for domain in domains)
    gated = sum(1 for domain in domains for row in (domain.get("topics") or [])
                if row.get("gated") and row.get("graded"))
    print(f"\n{gated} gated, {len(covered)} ungated by decision, "
          f"{total - gated - len(covered)} unaccounted for, of {total}")
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
