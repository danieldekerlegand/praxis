#!/usr/bin/env python3
"""A gap the library does not fill becomes a subject the shipped pipeline can build.

`praxis/gap.py` ends with a verdict per requirement. A verdict is not a tutorial: the
funnel only pays off if what comes out of it is the *same* thing a user gets by typing a
goal into Define, because everything downstream — `praxis/curriculum_gen.py`,
`scaffold_notebooks.py`, `praxis/construct.py`, `praxis/checks.py` — is already written
against that one input. So this band produces exactly one new artefact per gap, and it is
a **free-text goal string**:

    "I want to get hands-on with Terraform, well enough to use it in the job rather than
     just talk about it. A posting I'm targeting asks for it: "..."."

That string is what `curriculum_gen.generate_curriculum(goal)` takes, and it is all it
takes. There is no second constructor here, no suggestion-shaped curriculum format and
no branch anywhere downstream: an accepted suggestion is a hand-typed subject that
happened to be typed by this module.

Three properties keep a suggestion honest, and each is a test:

  - **No model.** Like band 76, the whole band is a rearrangement of what is already on
    the table — the requirement band 75 extracted and the verdict band 76 reached.
    `praxis/llm.py` is not imported here; the one model call this funnel makes has
    already been spent, and the next is the constructor's, after a human accepts.
  - **A suggestion never invents its reason.** `rationale` is band 76's own sentence
    (`why`), and `evidence` is band 76's citations verbatim — real notebooks, off the
    live index. What this module adds is the *consequence* of that sentence, never a
    fresh claim about the library.
  - **A `covered` requirement is not suggestable at all.** `SUGGESTABLE` is the two
    other verdicts, and `suggest_requirement` returns None for anything else, so the
    restraint the roadmap asks for is structural rather than a filter someone can
    forget.

Restraint is the hard half, though, and the verdict alone does not carry it. Band 76's
document is a *snapshot*: it was taken against the library as it stood, and between
then and a suggestion surviving, a curriculum can have been scaffolded, a domain added,
a recommended neighbour promoted. So every proposal is asked again, and asked of the
**live** index — `dedupe()` re-runs `gap.classify` over `curriculum.DOMAINS` as it is
now, and anything the library turns out to answer for is dropped:

  - a notebook **is** it (`shipped`), or every notebook that is it is a `recommended`
    neighbour already scaffolded in `curriculum.py` (`recommended`), or a whole
    **domain** is named for it (`domain`) — the three ways band 76 says `covered`;
  - or this same posting already proposed it under another name (`duplicate`): a
    posting that asks for "Kubernetes", "K8s experience" and "Kubernetes operators"
    wants one tutorial, not three.

Nothing is deleted quietly. A dropped proposal keeps its goal and its reason on the
document's `dropped` list, so band 78's review surface can show the restraint — and
un-drop one — rather than being handed a shorter list with no account of it.

A `partial` is the interesting case and the reason the goal is composed rather than
templated. The library touching a requirement is exactly what must *not* be re-taught:
"Kubernetes" is partial because *Kubernetes Jobsets* exists, so the goal it produces says
so — start from what that assumes, and teach the requirement itself.

CLI:
    python -m praxis.suggest "terraform" "kubernetes" "mlflow"
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import slugify  # noqa: E402
from praxis import gap  # noqa: E402
from praxis.library_index import (  # noqa: E402
    LibraryIndex,
    library_index,
    match_tokens,
)

SUGGEST_VERSION = 1

#: The verdicts that are a gap. `covered` is deliberately not here — see the module
#: docstring: restraint is the shape of this band, not a filter over its output.
SUGGESTABLE = ("missing", "partial")

#: Why a proposal did not survive `dedupe()`. The first three are the three ways band 76
#: says `covered`, re-asked of the live index; the fourth is the posting arguing with
#: itself. A drop is always one of these — there is no unexplained shortening.
DROP_REASONS = ("shipped", "recommended", "domain", "duplicate")

#: How a goal opens, by the kind band 75 gave the requirement. A learner types a goal in
#: the first person, so a suggestion does too — the string is indistinguishable from one
#: typed into Define, which is the whole claim of the band.
GOAL_OPENING = {
    "tool": "I want to get hands-on with {name}",
    "skill": "I want to get good at {name}",
    "competency": "I want to get good at {name}",
}
DEFAULT_OPENING = "I want to learn {name}"

#: What the posting's own required/preferred split asks of the depth of the tutorial.
GOAL_DEPTH = {
    "required": "well enough to use it in the job rather than just talk about it",
    "preferred": "well enough to be credible about it",
}
DEFAULT_DEPTH = GOAL_DEPTH["required"]

#: A quote is context for the model, not the posting: past this it is boilerplate.
MAX_QUOTE = 240

#: The adjacent notebooks a `partial` goal is told to start past. More than a few reads
#: as a reading list rather than a floor.
NEIGHBOUR_LIMIT = 3


class SuggestError(RuntimeError):
    """There was nothing to suggest from. The message says what was missing."""


# --- the goal string ----------------------------------------------------------


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _source_quote(row: dict) -> str:
    """The posting's own words for this requirement, whichever band handed them over.

    Band 76 folds its citations onto the requirement under `evidence` and carries band
    75's verbatim quote beside them as `quote`; a caller passing an unclassified
    requirement straight in still has it under `evidence`. Either way it is the string
    the extractor's validator found in `doc["text"]` — never something written here.
    """
    for key in ("quote", "evidence"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _quote(text: object) -> str:
    """One line of the posting, short enough to be context rather than the posting."""
    quote = " ".join(str(text or "").split())
    return quote[:MAX_QUOTE].rstrip() + "…" if len(quote) > MAX_QUOTE else quote


def neighbours(row: dict) -> list[dict]:
    """The notebooks band 76 cited for a `partial` — what a suggestion must not repeat."""
    if row.get("coverage") != "partial":
        return []
    return list(row.get("evidence") or ())[:NEIGHBOUR_LIMIT]


def _titles(rows: list[dict]) -> str:
    titles = [_text(r.get("title")) for r in rows if _text(r.get("title"))]
    if len(titles) > 1:
        return ", ".join(titles[:-1]) + " and " + titles[-1]
    return titles[0] if titles else ""


def goal_for(row: dict) -> str:
    """The free-text goal `curriculum_gen.generate_curriculum` takes, for one gap.

    Composed from what band 75 read out of the posting and what band 76 found in the
    library — a sentence for the ask, one for why it is being asked, and, for a
    `partial`, one saying which shipped notebooks the curriculum has to start past.
    """
    name = _text(row.get("name"))
    if not name:
        raise SuggestError("a suggestion needs a requirement name to propose a subject for")

    opening = GOAL_OPENING.get(_text(row.get("kind")).lower(), DEFAULT_OPENING)
    depth = GOAL_DEPTH.get(_text(row.get("importance")).lower(), DEFAULT_DEPTH)
    sentences = [f"{opening.format(name=name)}, {depth}."]

    quote = _quote(_source_quote(row))
    note = _text(row.get("note"))
    asks = "A job posting I'm targeting asks for it"
    if _text(row.get("importance")).lower() == "preferred":
        asks = "A job posting I'm targeting lists it as preferred"
    if note:
        asks += f" ({note})"
    if not quote:
        sentences.append(f"{asks}.")
    else:
        # The posting is quoted as written, so a quote that ends its own sentence keeps
        # its full stop rather than collecting a second one outside the quotation mark.
        stop = "" if quote.endswith((".", "!", "?")) else "."
        sentences.append(f"{asks}: \"{quote}\"{stop}")

    near = _titles(neighbours(row))
    if near:
        sentences.append(
            f"I have already studied {near}, so start from what that assumes and teach "
            f"{name} itself rather than covering it again."
        )
    return " ".join(sentences)


def rationale_for(row: dict) -> str:
    """Why this is a gap — band 76's sentence, plus what follows from it.

    Nothing here is a fresh claim about the library: `why` is quoted as band 76 wrote it,
    and the clause after it is the consequence the review surface acts on.
    """
    why = _text(row.get("why"))
    if not why:
        raise SuggestError(
            f"{_text(row.get('name')) or 'that requirement'} has no gap analysis to "
            "explain it — classify it against the library first"
        )
    if row.get("coverage") == "partial":
        return f"{why} — a tutorial here has to start past that material, not repeat it"
    return why


# --- one suggestion -----------------------------------------------------------


def _requirement(row: dict) -> dict:
    """The source requirement, carried through as band 75 wrote it."""
    return {
        "id": _text(row.get("id")) or slugify(_text(row.get("name"))),
        "name": _text(row.get("name")),
        "kind": _text(row.get("kind")),
        "importance": _text(row.get("importance")),
        "evidence": _source_quote(row),
        "note": _text(row.get("note")),
    }


def suggest_requirement(row: object) -> dict | None:
    """One classified requirement as a proposed subject, or None when it is not a gap.

    Takes a row of band 76's gap document — the requirement with its verdict folded in.
    `covered` (and anything else that is not a gap) returns None rather than raising:
    a whole list is classified at once and most of it is usually not suggestable.
    """
    if not isinstance(row, dict):
        raise SuggestError(f"a classified requirement is not an object "
                           f"(got {type(row).__name__})")
    if row.get("coverage") not in SUGGESTABLE:
        return None
    name = _text(row.get("name"))
    if not name:
        return None

    requirement = _requirement(row)
    return {
        "id": requirement["id"],
        "title": name,
        "goal": goal_for(row),
        "coverage": _text(row.get("coverage")),
        "rationale": rationale_for(row),
        "requirement": requirement,
        "evidence": list(row.get("evidence") or ()),
    }


# --- restraint: the library, then the posting itself --------------------------


def dedupe_key(row: dict) -> str:
    """One proposal's identity, as the phrase it would be a tutorial *about*.

    `gap.phrases` is the same pair of forms the classifier matched with, so the key is
    the requirement stripped of the words a posting wraps it in — "Advanced Kubernetes
    experience", "Kubernetes tooling" and "Kubernetes" are one key, and therefore one
    tutorial. Using the classifier's own normalizer is what keeps this from becoming a
    second opinion about what two requirements have in common.
    """
    tried = gap.phrases(_text(row.get("title")) or _text(row.get("name")))
    return tried[-1] if tried else ""


def _reason(verdict: dict) -> str:
    """Which of the three `covered` verdicts this is, as a drop reason."""
    evidence = list(verdict.get("evidence") or ())
    if any(cite.get("match") == "domain" for cite in evidence):
        return "domain"
    if evidence and all(cite.get("recommended") for cite in evidence):
        return "recommended"
    return "shipped"


def collides(proposal: dict, *, index: LibraryIndex | None = None) -> dict | None:
    """Does the library, as it stands *now*, already teach this? The drop, or None.

    The verdict on the proposal came off a snapshot; this asks `gap.classify` again over
    the live index, so a topic scaffolded since the analysis was taken still stops the
    re-tutorial. The reason and its sentence are band 76's — nothing here is a fresh
    claim about what ships.
    """
    index = index if index is not None else library_index()
    verdict = gap.classify(_text(proposal.get("title")), index=index)
    if verdict["coverage"] != "covered":
        return None
    return {
        "reason": _reason(verdict),
        "why": verdict["why"],
        "evidence": list(verdict["evidence"]),
    }


def _duplicate(proposal: dict, kept: list[dict]) -> dict | None:
    """Has this posting already proposed the same tutorial under another name?

    Equal keys are the same ask spelled differently. A key whose words *contain* another
    kept proposal's (or are contained by them) is the same ask at a different grain —
    "Kubernetes" and "Kubernetes operators" are one curriculum, and the curriculum
    generator is given the whole subject anyway. The earlier proposal wins, because the
    posting's own order is the only priority either band has.
    """
    key = dedupe_key(proposal)
    tokens = match_tokens(key)
    if not tokens:
        return None
    for other in kept:
        theirs = match_tokens(dedupe_key(other))
        if theirs and (tokens <= theirs or theirs <= tokens):
            return {
                "reason": "duplicate",
                "why": f"the posting already asks for this as {other['title']} — "
                       f"one tutorial covers both",
                "evidence": [],
                "duplicateOf": other["id"],
            }
    return None


def dedupe(
    proposals: list[dict], *, index: LibraryIndex | None = None
) -> tuple[list[dict], list[dict]]:
    """Hold the shipped library in mind, then the posting's own other asks.

    Returns `(kept, dropped)`. Two questions in that order: does the library already
    answer for this, and — only if it does not — has this posting already proposed it.
    A dropped proposal is returned whole, goal included, so band 78 can show what
    restraint cost rather than being handed a shorter list with no account of it.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for proposal in proposals:
        drop = collides(proposal, index=index) or _duplicate(proposal, kept)
        if drop is None:
            kept.append(proposal)
        else:
            dropped.append({**proposal, **drop})
    return kept, dropped


# --- a whole posting ----------------------------------------------------------


def _analysis(source: object, *, index: LibraryIndex | None = None) -> dict:
    """Band 76's gap document, whatever the caller had to hand.

    A document whose rows already carry a verdict is used as it is; anything else — band
    75's requirement document, or a bare list of names — is classified here, so a caller
    never has to run the two bands in the right order to get a suggestion.
    """
    if isinstance(source, dict):
        rows = source.get("requirements")
        if isinstance(rows, (list, tuple)) and rows and all(
            isinstance(r, dict) and r.get("coverage") in gap.COVERAGE for r in rows
        ):
            return source
    if source is None or (not isinstance(source, (dict, list, tuple))):
        raise SuggestError(
            "there is nothing to suggest from — analyze the posting's requirements first"
        )
    try:
        return gap.analyze(source, index=index)
    except gap.GapError as exc:
        raise SuggestError(str(exc)) from exc


def suggest(source: object, *, index: LibraryIndex | None = None) -> dict:
    """Every gap in a posting as a proposed subject, deduplicated. Band 78's document.

    Takes band 76's analysis (or anything `_analysis` can turn into one) and returns the
    surviving suggestions in the order the posting raised them, each carrying its goal
    string, its source requirement and its gap rationale. A `covered` requirement
    contributes nothing — it is not in the output and it is not counted as dropped,
    because it was never a candidate. A proposal the *live* library turns out to answer
    for, or that this posting has already made under another name, is on `dropped` with
    the reason; `counts` and `count` are over what survived.
    """
    index = index if index is not None else library_index()
    analysis = _analysis(source, index=index)
    rows = [r for r in analysis.get("requirements", ()) if isinstance(r, dict)]
    proposals = [s for s in (suggest_requirement(row) for row in rows) if s]
    suggestions, dropped = dedupe(proposals, index=index)
    return {
        "version": SUGGEST_VERSION,
        "jd": _text(analysis.get("jd")),
        "title": _text(analysis.get("title")),
        "suggested": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library": dict(analysis.get("library") or {}),
        "counts": {
            name: sum(1 for s in suggestions if s["coverage"] == name)
            for name in SUGGESTABLE
        },
        "count": len(suggestions),
        "dropCounts": {
            name: sum(1 for d in dropped if d["reason"] == name) for name in DROP_REASONS
        },
        "dropped": dropped,
        "droppedCount": len(dropped),
        "suggestions": suggestions,
    }


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2
    doc = suggest(list(argv))
    print(f"{doc['count']} suggestions from {len(argv)} requirements "
          f"({doc['counts']['missing']} missing, {doc['counts']['partial']} partial), "
          f"{doc['droppedCount']} dropped\n")
    for row in doc["suggestions"]:
        print(f"  {row['title']}  [{row['coverage']}]")
        print(f"      why:  {row['rationale']}")
        print(f"      goal: {row['goal']}\n")
    for row in doc["dropped"]:
        print(f"  - {row['title']}  [{row['reason']}]  {row['why']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
