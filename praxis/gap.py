#!/usr/bin/env python3
"""Covered, partially covered, or missing — what the library already answers for.

`praxis/jd_extract.py` says what a posting asks for; `praxis/library_index.py` says what
the product can already build. This band is the diff between them, and nothing more: for
each requirement, **one of three verdicts** and the topics that justify it.

The three come from `docs/explanation/gap-analysis.md`, which is the same judgement made
once by hand over the study list — §1 listed and covered, §2 the recommended neighbours
that were added anyway, §3 the legacy library nobody had listed. Read as a rule rather
than as three lists, that document says a requirement is:

  - **covered** — a topic *is* it. `LibraryIndex.lookup()` is that "is": both sides go
    through one normalizer, so "K8s" finds "Kubernetes" and "RAG pipelines" finds
    "Retrieval-Augmented Generation (RAG)". A `recommended` neighbour counts, because it
    is already scaffolded (§2) — building a second tutorial for it is exactly the
    redundancy this funnel exists to avoid. So does a whole domain named for the
    requirement: "Model Evaluation" is 12 notebooks, not a gap.
  - **partial** — no topic is it, but something adjacent touches it.
    `LibraryIndex.related()` scores adjacency, and `PARTIAL_FLOOR` is where this band
    draws the line. "Kubernetes" is partial: the library has *Kubernetes Jobsets* and
    nothing that teaches Kubernetes.
  - **missing** — neither. Terraform, Rust, incident response: the library says nothing.

Two properties keep it honest, and they are the reason this is not a model call:

  - **No model.** The verdict is a string match over the shipped corpus, so it is
    deterministic, needs no key, and cannot invent a topic. `praxis/llm.py` is not
    imported here — the funnel's one model call is band 75's, and it is already spent.
  - **Every verdict carries its evidence**, and every piece of evidence is a real
    notebook: `rel`, title, domain and whether it is a recommended neighbour, straight
    off the live index. `covered` with no evidence is not representable, which is what
    stops the classification from becoming an opinion band 77 has to trust.

Over-calling `covered` is the failure mode to fear, not under-calling it: a wrong
`covered` silently drops a requirement the learner needs. That is why adjacency alone
never earns `covered` no matter how high it scores — *Kubernetes Jobsets* accounts for
every word of "Kubernetes" and is still not a Kubernetes tutorial.

CLI:
    python -m praxis.gap "kubernetes" "mlflow" "terraform"     classify some phrases
    python -m praxis.gap --jd <jd-id>                          not this band (see 75/77)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis.library_index import (  # noqa: E402
    LibraryIndex,
    LibraryTopic,
    canonical_tokens,
    library_index,
    title_keys,
)

GAP_VERSION = 1

#: The coverage model of docs/explanation/gap-analysis.md, as three words.
COVERAGE = ("covered", "partial", "missing")

#: How much of a requirement's meaning an adjacent topic has to account for before it is
#: worth showing as "we have something near this". Below it, the topic shares a word or
#: two and no subject: that is a gap, and saying so is the point of the band.
PARTIAL_FLOOR = 0.4

#: A verdict is a citation, not a bibliography — band 77 writes a rationale from these.
EVIDENCE_LIMIT = 5

#: Words a posting wraps a requirement in that name nothing the library could teach.
#: Dropped only as a *second* attempt, so "Prompt Engineering" is matched as written
#: first and "Prompt engineering experience" still lands on the same notebook.
QUALIFIER_TOKENS = frozenset(
    "advanced deep strong solid proven modern production hand on experience expertise "
    "knowledge skill practice proficiency familiarity fundamental background exposure "
    "pipeline workflow tooling stack ecosystem".split()
)

#: A domain's title is a claim about a dozen notebooks, so it is matched more carefully
#: than a topic's: the whole title always, and a piece of it only when the piece is more
#: than one word. "Data Analysis" names a domain; "Research", on its own, names anything.
MIN_DOMAIN_KEY_TOKENS = 2


class GapError(RuntimeError):
    """There was no requirement list to classify. The message says what was missing."""


# --- what to match ------------------------------------------------------------


def phrases(name: object) -> tuple[str, ...]:
    """A requirement as written, then stripped of its qualifiers — tried in that order.

    Both forms go through `canonical_tokens`, the same normalizer the index built its
    keys with, so "Hands-on Kubernetes experience" and "Kubernetes" ask the same question.
    """
    tokens = canonical_tokens(name)
    core = [token for token in tokens if token not in QUALIFIER_TOKENS]
    out = [" ".join(tokens)] if tokens else []
    if core and core != tokens:
        out.append(" ".join(core))
    return tuple(out)


def domain_keys(index: LibraryIndex) -> dict[str, object]:
    """The names a whole domain answers to, keyed the way a topic is.

    Built off `index.domains`, which is `curriculum.DOMAINS` — live, like everything else
    in this funnel — so a domain added to the curriculum is matchable the same day.
    """
    keys: dict[str, object] = {}
    for domain in index.domains:
        candidates = title_keys(domain.title)
        for position, key in enumerate(candidates):
            if position == 0 or len(key.split()) >= MIN_DOMAIN_KEY_TOKENS:
                keys.setdefault(key, domain)
    return keys


# --- the verdict --------------------------------------------------------------


def _cite(topic: LibraryTopic, *, match: str, score: float) -> dict:
    """One notebook as evidence: what it is, where it is, and how it was matched."""
    return {**topic.evidence(), "match": match, "score": round(float(score), 3)}


def _verdict(coverage: str, why: str, evidence: list[dict]) -> dict:
    return {"coverage": coverage, "why": why, "evidence": evidence[:EVIDENCE_LIMIT]}


def _titles(evidence: list[dict]) -> str:
    return ", ".join(row["title"] for row in evidence[:EVIDENCE_LIMIT])


def classify(name: object, *, index: LibraryIndex | None = None) -> dict:
    """Classify one requirement phrase against the shipped library.

    Returns `{"coverage", "why", "evidence"}` — one of `COVERAGE`, a sentence a UI can
    show as written, and the notebooks that justify it (empty only for `missing`).
    """
    index = index if index is not None else library_index()
    label = str(name or "").strip()
    tried = phrases(label)
    if not tried:
        return _verdict("missing", "that requirement has no name to match", [])

    for phrase in tried:
        hits = index.lookup(phrase)
        if hits:
            evidence = [_cite(topic, match="exact", score=1.0) for topic in hits]
            scaffolded = all(topic.recommended for topic in hits)
            why = f"the library already teaches {label} — {_titles(evidence)}"
            if scaffolded:
                why += " (a recommended neighbour, already scaffolded)"
            return _verdict("covered", why, evidence)

    domains = domain_keys(index)
    for phrase in tried:
        domain = domains.get(phrase)
        if domain is not None:
            rows = [t for t in index.topics if t.domain == domain.dir]
            evidence = [_cite(topic, match="domain", score=1.0) for topic in rows]
            return _verdict(
                "covered",
                f"the library has a whole domain on {label} — {domain.title}, "
                f"{len(rows)} notebooks",
                evidence,
            )

    scored: list[tuple[LibraryTopic, float]] = []
    for phrase in tried:
        for topic, score in index.related(phrase):
            if score >= PARTIAL_FLOOR:
                scored.append((topic, score))
    if scored:
        best: dict[str, tuple[LibraryTopic, float]] = {}
        for topic, score in scored:
            if score > best.get(topic.rel, (topic, 0.0))[1]:
                best[topic.rel] = (topic, score)
        ranked = sorted(best.values(), key=lambda pair: (-pair[1], pair[0].title))
        evidence = [_cite(t, match="adjacent", score=s) for t, s in ranked]
        return _verdict(
            "partial",
            f"nothing in the library is {label}, but it is touched by "
            f"{_titles(evidence)}",
            evidence,
        )

    return _verdict("missing", f"nothing in the library addresses {label}", [])


def classify_requirement(requirement: object, *, index: LibraryIndex | None = None) -> dict:
    """One of band 75's requirements, with its verdict folded in.

    Lenient about what it is handed — a requirement document's entry, or a bare phrase —
    and it never drops a field the extractor wrote, because band 77 writes its suggestion
    from `kind` and `importance` as much as from the coverage.
    """
    if isinstance(requirement, str):
        requirement = {"name": requirement}
    if not isinstance(requirement, dict):
        raise GapError(f"a requirement is not an object (got {type(requirement).__name__})")
    return {**requirement, **classify(requirement.get("name"), index=index)}


def analyze(requirements: object, *, index: LibraryIndex | None = None) -> dict:
    """Classify a whole requirement list. Takes band 75's document or its list.

    The result is the gap document band 77 reads: every requirement in the order the
    posting raised it, each with its verdict, plus the counts and the size of the library
    the verdicts were taken against — so a run can be read back knowing which corpus it
    saw.
    """
    doc: dict = {}
    if isinstance(requirements, dict):
        doc = requirements
        requirements = doc.get("requirements")
    if not isinstance(requirements, (list, tuple)) or not requirements:
        raise GapError(
            "there are no requirements to classify — extract them from the posting first"
        )

    index = index if index is not None else library_index()
    rows = [classify_requirement(item, index=index) for item in requirements]
    return {
        "version": GAP_VERSION,
        "jd": str(doc.get("jd") or doc.get("id") or ""),
        "title": str(doc.get("title") or ""),
        "analyzed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": list(COVERAGE),
        "counts": {name: sum(1 for r in rows if r["coverage"] == name) for name in COVERAGE},
        "library": {"domains": len(index.domains), "topics": len(index)},
        "count": len(rows),
        "requirements": rows,
    }


def gaps(analysis: dict) -> list[dict]:
    """The requirements the library does not already teach — band 77's input."""
    return [r for r in analysis.get("requirements", []) if r.get("coverage") != "covered"]


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2
    analysis = analyze(list(argv))
    counts = analysis["counts"]
    print(f"{analysis['count']} requirements against {analysis['library']['topics']} "
          f"notebooks: " + ", ".join(f"{n} {name}" for name, n in counts.items()) + "\n")
    mark = {"covered": "=", "partial": "~", "missing": " "}
    for row in analysis["requirements"]:
        print(f"  {mark[row['coverage']]} {row['name']:<28} {row['coverage']:<9} {row['why']}")
        for cite in row["evidence"]:
            print(f"      {cite['score']:.2f} {cite['match']:<8} {cite['rel']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
