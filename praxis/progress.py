#!/usr/bin/env python3
"""Learner progress — the half of the gate that says what is unlocked.

`praxis/checks.py` writes the questions; this decides what they gate. Nothing here
calls a model and nothing here grades: `checks.grade()` produces a `CheckOutcome`, this
records it and derives what the learner may reach next. Keeping the two apart is what
makes the gate honest — an unlock is a *function* of recorded outcomes, never a flag
somebody set.

The rule, in one sentence: **a section is unlocked when every check in every earlier
section has a passing outcome.** The first gated section is always open, order is
`checks.GATED_SECTIONS` (the rubric's own order), and the same rule one level up gates
the topics of a module: a topic is locked while an earlier topic in the same module
still has unpassed checks.

A topic with no checks beside it gates nothing. That is deliberate and is what keeps
the seed library browsable: 221 hand-written notebooks have no `<slug>.checks.json`, so
there is no gate to be stuck behind. Gating only ever appears where the constructor
actually wrote questions.

Progress persists as one JSON file per learner under `progress_dir()` — beside the
learner's subjects on whichever backend `praxis/storage.py` says is active, so closing
the app and reopening it resumes where the learner stopped. What is stored
is the whole `CheckOutcome` — including the learner's answer verbatim and who graded
it — not a boolean, because "did they pass" is a record, not a bit.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import slugify  # noqa: E402
from praxis import storage  # noqa: E402
from praxis.checks import (  # noqa: E402
    GATED_SECTIONS,
    CheckOutcome,
    checks_by_section,
    learner_check,
)

PROGRESS_VERSION = 1
DEFAULT_LEARNER = "default"


def progress_dir() -> Path:
    """Where learner progress is kept — the active storage backend decides.

    Beside the learner's subjects under `praxis.storage`'s root, so choosing a backend
    moves what they built and how far they got together. `PRAXIS_PROGRESS_DIR` still
    relocates just this leaf (tests).
    """
    return storage.progress_dir()


def learner_id(name: object) -> str:
    """A learner name squashed to something safe as a filename."""
    return slugify(str(name or ""), fallback=DEFAULT_LEARNER)


def progress_path(learner: str = DEFAULT_LEARNER) -> Path:
    return progress_dir() / f"{learner_id(learner)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_progress(learner: str = DEFAULT_LEARNER) -> dict:
    return {
        "version": PROGRESS_VERSION,
        "learner": learner_id(learner),
        "updated": "",
        "topics": {},
    }


def load_progress(learner: str = DEFAULT_LEARNER) -> dict:
    """This learner's record, or an empty one. Unreadable/foreign files read as empty.

    Never raises: a learner whose file was hand-edited into nonsense starts over rather
    than locking themselves out of the app.
    """
    try:
        data = json.loads(progress_path(learner).read_text())
    except (OSError, ValueError):
        return empty_progress(learner)
    if not isinstance(data, dict) or data.get("version") != PROGRESS_VERSION:
        return empty_progress(learner)
    if not isinstance(data.get("topics"), dict):
        data["topics"] = {}
    return data


def save_progress(doc: dict) -> Path:
    path = progress_path(doc.get("learner", DEFAULT_LEARNER))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated"] = _now()
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def topic_outcomes(doc: dict, rel: str) -> dict[str, dict]:
    """check_id -> the stored outcome, for one notebook. `{}` when it is untouched."""
    entry = (doc.get("topics") or {}).get(str(rel))
    outcomes = entry.get("outcomes") if isinstance(entry, dict) else None
    return outcomes if isinstance(outcomes, dict) else {}


def record_outcome(learner: str, rel: str, outcome: CheckOutcome) -> dict:
    """Store one graded answer and return the updated record. The only write here.

    The latest answer to a check replaces the previous one, pass or fail — a learner may
    retry, and a check they later get wrong genuinely does close the sections it gates.
    """
    doc = load_progress(learner)
    topics = doc.setdefault("topics", {})
    entry = topics.setdefault(str(rel), {"outcomes": {}})
    if not isinstance(entry.get("outcomes"), dict):
        entry["outcomes"] = {}
    entry["outcomes"][outcome.check_id] = outcome.to_dict()
    entry["updated"] = _now()
    save_progress(doc)
    return doc


# --- the gate over one notebook ---------------------------------------------


@dataclass(frozen=True)
class SectionGate:
    """One section of one notebook, as the learner may see it right now."""

    section: str
    checks: tuple[dict, ...]
    locked: bool
    passed: int

    @property
    def n(self) -> int:
        return len(self.checks)

    @property
    def complete(self) -> bool:
        return self.passed == self.n

    def to_dict(self, outcomes: dict[str, dict]) -> dict:
        """The learner's view. A locked section serves no questions — only its size.

        Answer keys never cross this boundary (`checks.learner_check`), and a locked
        section hands over nothing at all, so neither the answers nor the questions of
        a section the learner has not reached are readable from the app.
        """
        return {
            "section": self.section,
            "locked": self.locked,
            "complete": self.complete,
            "passed": self.passed,
            "n": self.n,
            "checks": [] if self.locked else [
                learner_check(c, outcomes.get(str(c.get("id", "")))) for c in self.checks
            ],
        }


def section_gates(doc: dict | None, outcomes: dict[str, dict]) -> list[SectionGate]:
    """Every gated section in rubric order, with what the learner has unlocked.

    Pure — the whole progression rule is these six lines, so it can be reasoned about
    and tested without a filesystem, an app or a model.
    """
    if not doc:
        return []
    by_section = checks_by_section(doc)
    gates: list[SectionGate] = []
    open_ = True  # the first gated section is always reachable
    for section in GATED_SECTIONS:
        checks = tuple(by_section.get(section, ()))
        passed = sum(1 for c in checks
                     if (outcomes.get(str(c.get("id", ""))) or {}).get("passed"))
        gate = SectionGate(section=section, checks=checks, locked=not open_, passed=passed)
        gates.append(gate)
        open_ = open_ and gate.complete
    return gates


def gate_for(doc: dict | None, outcomes: dict[str, dict], check_id: str) -> SectionGate | None:
    """The section gate a check belongs to — how "may they answer this?" is decided."""
    return next(
        (g for g in section_gates(doc, outcomes)
         if any(str(c.get("id", "")) == str(check_id) for c in g.checks)),
        None,
    )


def unlocked_sections(doc: dict | None, outcomes: dict[str, dict]) -> list[str]:
    return [g.section for g in section_gates(doc, outcomes) if not g.locked]


def topic_progress(doc: dict | None, outcomes: dict[str, dict]) -> dict:
    """How far through one notebook a learner is. `gated` is False when it has no set."""
    gates = section_gates(doc, outcomes)
    passed = sum(g.passed for g in gates)
    total = sum(g.n for g in gates)
    return {
        "gated": bool(gates and total),
        "passed": passed,
        "n": total,
        "complete": bool(total) and passed == total,
        "unlocked": [g.section for g in gates if not g.locked],
        "next": next((g.section for g in gates if not g.locked and not g.complete), ""),
    }


# --- the same rule one level up: topics within a module ---------------------


def module_gates(
    rels: list[str], docs: dict[str, dict | None], progress: dict
) -> dict[str, dict]:
    """rel -> {gated, complete, locked, blockedBy} for one module's topics, in order.

    A topic is locked while any *earlier* topic in the module is gated and unfinished.
    Ungated topics (no checks beside them) never lock anything, which is why the seed
    library reads exactly as it did before there was a gate at all.
    """
    state: dict[str, dict] = {}
    blocker = ""
    for rel in rels:
        doc = docs.get(rel)
        summary = topic_progress(doc, topic_outcomes(progress, rel))
        state[rel] = {
            "gated": summary["gated"],
            "complete": summary["complete"],
            "passed": summary["passed"],
            "checks": summary["n"],
            "locked": bool(blocker),
            "blockedBy": blocker,
        }
        if summary["gated"] and not summary["complete"] and not blocker:
            blocker = rel
    return state
