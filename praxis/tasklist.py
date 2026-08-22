"""Chief tasklists for a unit of praxis batch work — one domain's gate, one subject's build.

Praxis already owns the batch. `construct_each` is the one loop; `backfill_domain`
selects a domain's ✅-but-ungated notebooks for it and `construct_subject` hands it a
whole generated curriculum. What praxis does not own is **unattended volume** — running
that loop over the library with nobody in front of the app. That is Chief's job, and a
Chief tasklist is the unit Chief runs.

This module is the adapter between the two, and it is deliberately a **generator, not a
second batch**: nothing here constructs a notebook or writes a gate. It reads the live
library, cuts it into units of work, and emits `tasks/chief/<name>.json` whose stories
run the *shipped* commands —

    gate-<domain.dir>    python3 -m praxis.backfill <domain.dir>
    build-<subject.slug> python3 -m praxis.construct --subject <subject.slug>

— so the anti-fabrication bar a Chief-driven run clears is exactly the one an in-app run
clears, for the reason that it is the same code path. A tasklist that drove its own
construction would be a second definition of "complete", and the two would drift.

Three properties are worth naming, because they are the argument that an unattended run
is safe:

- **Resumability is not written here.** It falls out of the shipped contracts — an
  already-✅ notebook is skipped by `construct_topic`, an already-gated topic is not
  even selected by `backfill.is_gated` — so a headless retry, a Chief iteration that
  ran out of budget mid-batch, and a re-run of a finished tasklist all pick up exactly
  what is left and rewrite nothing that was good. That is why `iters` scales with the
  backlog rather than with anything else: another iteration is another resumed pass.
- **A unit with nothing to do is not a tasklist.** `unit_for` raises rather than emit
  one, because an empty tasklist is a run that ends `EMPTY-NO-WORK` — an hour of driver
  time spent proving the library was already gated.
- **A generated tasklist is graded before it is written**, the same rule the constructor
  and the check writer follow: `tasklist_failures()` is the machine-readable definition
  of "well-formed" (branch, category, stories, no `mergedToMain`), and `write_tasklist`
  never writes a document that fails it.

`touches` is the one scheduler field that carries a decision. A unit declares the
notebook tree it writes into (`notebooks/<dir>`, or `subjects/<slug>`), so two tasklists
gating the *same* domain are never co-scheduled while fourteen gating fourteen different
domains run in parallel — which is the whole point of driving the backfill this way.

`praxis/headless.py` is the other half: it takes what this writes and runs it through
Chief's headless entry point.

CLI:
    python3 -m praxis.tasklist                    # the units the library offers
    python3 -m praxis.tasklist show <name>        # one unit's live plan
    python3 -m praxis.tasklist write <name> [--force]
    python3 -m praxis.tasklist write --jd <jd-id> # the subjects accepted off one posting
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import (  # noqa: E402
    CurriculumError,
    Domain,
    Subject,
    Topic,
    all_subjects,
    load_subject,
)
from praxis import backfill  # noqa: E402

PROJECT = "praxis"
BASE_BRANCH = "main"
TASKLIST_DIR = "tasks/chief"

# The category vocabulary is `scripts/check-tasklist-categories.mjs`'s, restated here
# because a generated tasklist has to clear that guard the day it lands. A gating
# backfill repairs a gate that is real but sparse (`fix`, which is what 79 declared
# itself); a JD-accepted subject is net-new capability (`feature`).
CATEGORIES = ("fix", "unblock", "replace", "feature")

# One iteration is one resumed pass over the backlog, so a bigger backlog is not a
# harder story — it is more passes. Bounded at both ends: three so a stalled iteration
# has somewhere to go, twelve so a domain nobody can gate does not spend a whole run.
MIN_ITERS, MAX_ITERS, TOPICS_PER_ITER = 3, 12, 5


class TasklistError(ValueError):
    """A unit that cannot become a tasklist, named with what to do instead."""


@dataclass(frozen=True)
class Unit:
    """One unit of praxis batch work, sized and named the way Chief will run it."""

    name: str                      # the tasklist stem — and `chief/<name>`
    kind: str                      # "backfill" | "subject"
    slug: str                      # the domain's `dir`, or the subject's `slug`
    title: str
    command: str                   # the shipped entry point this tasklist drives
    pending: tuple[str, ...]       # the notebooks it would touch, in batch order
    done: int                      # what is already ✅-and-gated, for the description
    touches: tuple[str, ...]
    category: str

    @property
    def branch(self) -> str:
        return f"chief/{self.name}"

    def summary(self) -> str:
        return (f"{self.name:<34} {len(self.pending):>3} pending, {self.done:>3} done"
                f"  ({self.command})")


def _rel(domain: Domain, topic: Topic) -> str:
    """`Domain.dir` is always relative to the notebooks root — the library's own `rel`."""
    return f"{domain.dir}/{topic.slug}.ipynb"


# --- the two units ----------------------------------------------------------


def backfill_unit(domain: Domain, *, subject: Subject | None = None) -> Unit:
    """One domain's gating backfill: its ✅-but-ungated notebooks, in library order.

    The selection is `backfill.backfill_targets` and nothing else, so what the tasklist
    promises is exactly what the command it names will pick up — including the two rules
    that keep the run honest: a notebook that is not yet ✅ is left for construction
    rather than force-gated, and one that is already gated is not a target at all.
    """
    targets = backfill.backfill_targets(domain, subject=subject)
    complete = [(d, t) for d, t, _ in backfill.domain_targets(domain, subject=subject)
                if backfill.is_complete(d, t)]
    return Unit(
        name=f"gate-{domain.dir.replace('/', '-')}",
        kind="backfill",
        slug=domain.dir,
        title=domain.title,
        command=f"python3 -m praxis.backfill {domain.dir}",
        pending=tuple(_rel(d, t) for d, t, _ in targets),
        done=sum(1 for d, t in complete if backfill.is_gated(d, t)),
        touches=(f"notebooks/{domain.dir}",),
        category="fix",
    )


def subject_unit(subject: Subject) -> Unit:
    """One generated subject's build: every topic that is not yet ✅ **and** gated.

    Wider than a backfill on purpose — a subject arrives scaffolded (or not scaffolded
    at all), so the same command has to construct the prose and write the gate, which is
    what `construct_subject` already does in one pass per topic.
    """
    pending: list[str] = []
    done = 0
    for module in subject.modules:
        for topic in module.topics:
            if backfill.is_complete(module, topic) and backfill.is_gated(module, topic):
                done += 1
            else:
                pending.append(_rel(module, topic))
    return Unit(
        name=f"build-{subject.slug}",
        kind="subject",
        slug=subject.slug,
        title=subject.title,
        command=f"python3 -m praxis.construct --subject {subject.slug}",
        pending=tuple(pending),
        done=done,
        touches=(f"subjects/{subject.slug}",),
        category="feature",
    )


def library_units(*, subjects: bool = False) -> list[Unit]:
    """Every unit the live library offers, with an empty backlog left in.

    `unit_for` refuses an empty one — a report of what is left to drive must still show
    the domains that are finished, so the filtering happens at the caller.
    """
    units = [backfill_unit(domain, subject=subject)
             for domain, subject in backfill.library_domains()]
    if subjects:
        units += [subject_unit(s) for s in all_subjects()]
    return units


def unit_for(name: str) -> Unit:
    """Resolve a unit by its tasklist name, refusing one there is no work for."""
    unit = next((u for u in library_units(subjects=True) if u.name == name), None)
    if unit is None:
        raise TasklistError(
            f"no unit named '{name}' — `python3 -m praxis.tasklist` lists what there is "
            f"(a domain's gate is 'gate-<domain-dir>', a subject's build 'build-<slug>')"
        )
    if not unit.pending:
        raise TasklistError(
            f"'{name}' has nothing to do: {unit.done} topics are already complete and "
            f"gated. Emitting a tasklist for it would spend a Chief run proving so."
        )
    return unit


def accepted_units(jd_id: str) -> list[Unit]:
    """The subjects accepted off one job posting, as units (band 78's `accepted`).

    An accepted suggestion already carries the slug of a subject that was generated and
    saved when the reviewer accepted it, so this resolves rather than invents: a slug
    whose subject is no longer on disk is reported, not guessed at.
    """
    from praxis import suggestion_review  # noqa: PLC0415  (storage, not a core dependency)

    review = suggestion_review.load(jd_id)
    if review is None:
        raise TasklistError(f"no suggestion review for job description '{jd_id}'")
    units, missing = [], []
    for row in review.get("accepted") or ():
        slug = str((row or {}).get("slug") or "").strip() if isinstance(row, dict) else ""
        if not slug:
            continue
        try:
            units.append(subject_unit(load_subject(slug)))
        except CurriculumError:
            missing.append(slug)
    if not units:
        raise TasklistError(
            f"job description '{jd_id}' has no accepted subject on disk"
            + (f" (missing: {', '.join(missing)})" if missing else
               " — accept a suggestion first")
        )
    return units


# --- the tasklist -----------------------------------------------------------


def _iters(pending: int) -> int:
    return max(MIN_ITERS, min(MAX_ITERS, 2 + (pending + TOPICS_PER_ITER - 1)
                              // TOPICS_PER_ITER))


def _description(unit: Unit) -> str:
    n = len(unit.pending)
    if unit.kind == "backfill":
        what = (f"Gate {unit.title}: {n} of the domain's ✅ notebooks carry no knowledge "
                f"checks ({unit.done} are already gated).")
        where = f"The notebooks are in the branch, under notebooks/{unit.slug}/."
    else:
        what = (f"Build {unit.title}: {n} of the subject's topics are not yet ✅ and "
                f"gated ({unit.done} are).")
        where = ("A generated subject is the user's data and is written OUTSIDE the "
                 "repo — under praxis.storage's root (PRAXIS_SUBJECTS_DIR) — so this "
                 "tasklist's artifacts are on disk there, not in the branch's diff.")
    return (
        f"{what} Generated by praxis.tasklist from the live library, and it adds no "
        f"construction or gating primitive of its own: the stories run the shipped "
        f"entry point `{unit.command}`, which is praxis's one batch loop "
        f"(construct_each → construct_topic → praxis/checks.py over GATED_SECTIONS) "
        f"reached from the command line instead of from the app. {where} Resumability "
        f"is not implemented here either — it falls out of the shipped skip-if-✅ "
        f"(construct_topic) and skip-if-gated (backfill.is_gated) contracts, so an "
        f"unattended or retried run selects only what is still missing and never "
        f"rewrites a good notebook or a passing checkset. Anti-fabrication: content "
        f"that fails the grader is never written, a checkset whose reference solution "
        f"does not pass its own test is never written, and a topic the model could not "
        f"finish is reported and left as it was — the count only moves for artifacts "
        f"that actually landed."
    )


def _stories(unit: Unit) -> list[dict]:
    n = len(unit.pending)
    if unit.kind == "backfill":
        evidence = (f"`python3 scripts/validate_nbgrader.py notebooks/{unit.slug}` "
                    f"passes (record the notebook count it reports)")
        first = f"Gate {unit.title}'s ungated notebooks with the shipped backfill"
    else:
        evidence = ("every notebook it wrote reports ✅ from nbstatus and carries "
                    "nbgrader graded cells (record how many of the "
                    f"{n} topics landed)")
        first = f"Construct and gate {unit.title} with the shipped constructor"
    plan = f"python3 -m praxis.tasklist show {unit.name}"
    return [
        {
            "id": "US-1",
            "title": first,
            "acceptanceCriteria": [
                f"Run `{unit.command}` in this worktree. It drives the shipped batch "
                f"loop over the {n} topics `{plan}` lists — write no new construction "
                f"or gating code here, and change no rule in praxis/rubric.py, "
                f"praxis/checks.py or praxis/gateaudit.py to make a topic pass.",
                f"Every artifact that landed clears the shipped bar: {evidence}.",
                "A topic the model could not finish is left as it was and reported — "
                "no notebook is marked complete that the grader rejected, and no "
                "checkset that fails checkset_failures is written to move the number.",
                f"Gate green: `python3 -m pytest -q tests/` passes (record the counts), "
                f"and record the backlog `{plan}` reports before and after the run.",
            ],
            "passes": False,
            "notes": "",
        },
        {
            "id": "US-2",
            "title": "Prove the pass is resumable: a re-run does the remainder, nothing else",
            "acceptanceCriteria": [
                f"Re-run `{unit.command}`: it selects only what is still missing, "
                f"because an already-✅ notebook is skipped by construct_topic and an "
                f"already-gated topic is not a target at all — this is the property "
                f"that makes an unattended headless retry safe, so it is measured, not "
                f"assumed.",
                "Nothing the first pass produced is rewritten by the second: record "
                "`git status --porcelain` (a backfill's notebooks are in the branch) "
                "or the unchanged mtimes/digests of the artifacts the first pass wrote.",
                "Gate green: `python3 -m pytest -q tests/` passes (record the counts).",
            ],
            "passes": False,
            "notes": "",
        },
    ]


def tasklist(unit: Unit) -> dict:
    """One unit as a Chief tasklist document. Graded by `tasklist_failures` before use."""
    return {
        "name": None,
        "project": PROJECT,
        "category": unit.category,
        "branchName": unit.branch,
        "baseBranch": BASE_BRANCH,
        "description": _description(unit),
        "parked": False,
        "dependsOn": [],
        "touches": list(unit.touches),
        "iters": _iters(len(unit.pending)),
        "warmup": [f"python3 -m praxis.tasklist show {unit.name}"],
        "userStories": _stories(unit),
    }


# --- the grader -------------------------------------------------------------


def tasklist_failures(doc: object, *, name: str | None = None) -> list[str]:
    """What is wrong with this document as a Chief tasklist, in the grader's own words.

    The machine-readable half of `docs/reference/tasklist-schema.md` as praxis needs it:
    a document that passes this is valid JSON, runs on `chief/<name>`, declares a
    category `scripts/check-tasklist-categories.mjs` accepts, carries stories nobody has
    marked done, and claims no merge that has not happened. Nothing that fails it is
    written — the same rule the constructor and the check writer follow.
    """
    failures: list[str] = []
    if not isinstance(doc, dict):
        return [f"a tasklist is a JSON object, not {type(doc).__name__}"]
    try:
        json.dumps(doc)
    except (TypeError, ValueError) as exc:
        failures.append(f"the tasklist is not JSON-serializable: {exc}")

    for field in ("project", "branchName", "baseBranch", "description"):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            failures.append(f"'{field}' must be a non-empty string")
    if doc.get("project") != PROJECT:
        failures.append(f"'project' must be '{PROJECT}' (got {doc.get('project')!r})")
    if doc.get("category") not in CATEGORIES:
        failures.append(f"'category' must be one of {' | '.join(CATEGORIES)} "
                        f"(got {doc.get('category')!r})")
    if name is not None and doc.get("branchName") != f"chief/{name}":
        failures.append(f"'branchName' must be 'chief/{name}' "
                        f"(got {doc.get('branchName')!r})")
    elif isinstance(doc.get("branchName"), str) and not doc["branchName"].startswith("chief/"):
        failures.append(f"'branchName' must start with 'chief/' (got {doc['branchName']!r})")
    if "mergedToMain" in doc:
        failures.append("'mergedToMain' is written by chief when a branch merges, "
                        "never by a generator")
    if not isinstance(doc.get("iters"), int) or doc["iters"] < 1:
        failures.append("'iters' must be a positive integer")
    for field in ("touches", "warmup", "dependsOn"):
        value = doc.get(field)
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            failures.append(f"'{field}' must be a list of strings")

    stories = doc.get("userStories")
    if not isinstance(stories, list) or not stories:
        failures.append("'userStories' must be a non-empty list")
        return failures
    seen: set[str] = set()
    for index, story in enumerate(stories, start=1):
        where = f"story {index}"
        if not isinstance(story, dict):
            failures.append(f"{where} is not an object")
            continue
        sid = story.get("id")
        where = f"story {sid or index}"
        if not isinstance(sid, str) or not sid.strip():
            failures.append(f"{where} has no 'id'")
        elif sid in seen:
            failures.append(f"story id '{sid}' is used twice")
        else:
            seen.add(sid)
        if not isinstance(story.get("title"), str) or not story["title"].strip():
            failures.append(f"{where} has no 'title'")
        criteria = story.get("acceptanceCriteria")
        if not isinstance(criteria, list) or not criteria or any(
            not isinstance(c, str) or not c.strip() for c in criteria
        ):
            failures.append(f"{where} needs a non-empty list of acceptance criteria")
        if story.get("passes") is not False:
            failures.append(f"{where} must be generated with 'passes': false "
                            f"(got {story.get('passes')!r})")
    return failures


# --- writing it ------------------------------------------------------------


def repo_root() -> Path:
    """The praxis checkout this module lives in — where `tasks/chief` is."""
    return Path(__file__).resolve().parent.parent


def tasklist_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / TASKLIST_DIR


def write_tasklist(unit: Unit, *, root: Path | None = None, force: bool = False) -> Path:
    """Emit `tasks/chief/<name>.json`. Never writes a document that fails the grader.

    Refuses to overwrite by default, and the completed record counts: a tasklist that is
    already in flight carries stories Chief has marked done, and one that is retired
    carries the sha it merged at. Regenerating over either would reset bookkeeping that
    is not this module's to reset — so it says which one it found and stops.
    """
    directory = tasklist_dir(root)
    path = directory / f"{unit.name}.json"
    retired = directory / "completed" / f"{unit.name}.json"
    if not force:
        for existing, what in ((path, "is already active"), (retired, "has been retired")):
            if existing.is_file():
                raise TasklistError(
                    f"'{unit.name}' {what} ({existing}) — re-generating would overwrite "
                    f"chief's own bookkeeping. Pass force=True (--force) to replace it."
                )
    doc = tasklist(unit)
    failures = tasklist_failures(doc, name=unit.name)
    if failures:
        raise TasklistError(
            f"the generated tasklist for '{unit.name}' is not well-formed: "
            + "; ".join(failures)
        )
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def write_each(
    units: Iterable[Unit], *, root: Path | None = None, force: bool = False
) -> list[Path]:
    return [write_tasklist(unit, root=root, force=force) for unit in units]


# --- CLI --------------------------------------------------------------------


def render(units: Sequence[Unit]) -> str:
    """The units the library offers, most work first — what there is to drive."""
    rows = sorted(units, key=lambda u: (-len(u.pending), u.name))
    lines = [u.summary() for u in rows]
    lines.append("")
    lines.append(f"{sum(len(u.pending) for u in rows)} topics pending across "
                 f"{sum(1 for u in rows if u.pending)} of {len(rows)} units")
    return "\n".join(lines)


def _show(unit: Unit) -> str:
    lines = [unit.summary(), ""]
    lines += [f"  {rel}" for rel in unit.pending]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Chief tasklists for a unit of praxis batch work"
    )
    sub = parser.add_subparsers(dest="cmd")
    listing = sub.add_parser("list", help="the units the live library offers")
    listing.add_argument("--subjects", action="store_true",
                         help="include generated subjects, not just the seed domains")
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="one unit's live plan (the generated warmup)")
    show.add_argument("name")
    write = sub.add_parser("write", help="emit tasks/chief/<name>.json")
    write.add_argument("names", nargs="*")
    write.add_argument("--jd", default="", help="write one per subject accepted off a posting")
    write.add_argument("--force", action="store_true", help="replace an existing tasklist")
    args = parser.parse_args(argv)

    try:
        if args.cmd in (None, "list"):
            units = library_units(subjects=getattr(args, "subjects", False))
            if getattr(args, "json", False):
                json.dump([u.__dict__ for u in units], sys.stdout, indent=2, default=list)
                sys.stdout.write("\n")
            else:
                print(render(units))
            return 0
        if args.cmd == "show":
            print(_show(unit_for(args.name)))
            return 0
        units = ([unit_for(n) for n in args.names]
                 + (accepted_units(args.jd) if args.jd else []))
        if not units:
            parser.error("name a unit to write, or pass --jd <id>")
        for path in write_each(units, force=args.force):
            print(path)
        return 0
    except TasklistError as exc:
        print(f"praxis.tasklist: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
