#!/usr/bin/env python3
"""What a posting actually asks for — the one model-backed step of the JD funnel.

`praxis/jd.py` turns whatever the user brought (a paste, a .docx, a print-to-PDF) into
one canonical plain text. That text is prose: a human reads "Deep Kubernetes experience:
you have debugged a CNI, not just applied YAML" and knows it is one requirement, but
nothing downstream can diff prose against what a learner already knows. This band asks
the model to read that text once and hand back the **structured list** the gap analysis
needs — each requirement a normalized name, a kind (skill · tool · competency) and the
span of the posting it came from.

It is `praxis/curriculum_gen.py`'s house style, one funnel over:

    ask for JSON  ->  extract_json (fenced or bare, prose notwithstanding)
                  ->  normalize leniently (kind aliases, an omitted importance, a note)
                  ->  validate strictly, and only then is there a requirement list

The strict half is `requirements_failures()`, modelled on `curriculum.subject_from_dict`:
forgiving about everything the model may omit, unforgiving about anything the gap-analysis
band would choke on. Nothing is coerced past it — a payload that fails comes back as a
`JDExtractError` carrying the grader's own sentences, and there is no partial list.

One rule carries the anti-fabrication weight, and it is the reason `evidence` is not
decoration: **a requirement's evidence must really appear in the posting.** It is checked
by looking for it (whitespace- and case-insensitively) in `doc["text"]`, so a model that
infers a plausible requirement the posting never asked for cannot get it past the
validator by writing a plausible quote to go with it. That is this band's equivalent of
`praxis/checks.py` *running* a reference solution rather than reading it.

The model is not optional here. There is no local extractor to fall back on — with no key
configured, `praxis.llm.load_config()` raises `LLMConfigError` and this raises it too,
which is the 503 the launcher answers with for short-answer grading.

CLI:
    python -m praxis.jd_extract <jd-id>          extract, print the requirements
    python -m praxis.jd_extract --list           what has been imported (ids to pass)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import slugify  # noqa: E402
from praxis import jd  # noqa: E402
from praxis.curriculum_gen import extract_json  # noqa: E402
from praxis.llm import LLMClient, LLMError  # noqa: E402

REQUIREMENTS_VERSION = 1

#: What a posting asks for, split the three ways the gap analysis can act on:
#: something you can *do*, something you use to do it, and how you work.
KINDS = ("skill", "tool", "competency")

#: What the model calls them when it isn't reading carefully.
KIND_ALIASES = {
    "skill": "skill", "skills": "skill", "technical-skill": "skill",
    "technical_skill": "skill", "technique": "skill", "ability": "skill",
    "tool": "tool", "tools": "tool", "technology": "tool", "tech": "tool",
    "platform": "tool", "language": "tool", "framework": "tool", "product": "tool",
    "competency": "competency", "competencies": "competency", "competence": "competency",
    "soft-skill": "competency", "soft_skill": "competency", "behaviour": "competency",
    "behavior": "competency", "practice": "competency", "responsibility": "competency",
    "experience": "competency",
}

#: A posting's own division: what it requires, and what it would merely like.
IMPORTANCE = ("required", "preferred")
IMPORTANCE_ALIASES = {
    "required": "required", "require": "required", "must": "required",
    "must-have": "required", "must_have": "required", "essential": "required",
    "core": "required", "mandatory": "required",
    "preferred": "preferred", "prefer": "preferred", "nice": "preferred",
    "nice-to-have": "preferred", "nice_to_have": "preferred", "bonus": "preferred",
    "desirable": "preferred", "optional": "preferred", "plus": "preferred",
}

DEFAULT_LIMIT = 30      # a posting asks for a page of things, not a hundred
MAX_LIMIT = 60
JD_EXCERPT = 24000      # a posting is a few pages; anything past this is boilerplate

MIN_NAME_CHARS = 2
MAX_NAME_CHARS = 80
MIN_EVIDENCE_CHARS = 12  # shorter than this quotes nothing a human could check

SYSTEM_PROMPT = (
    "You are a technical recruiter who reads a job posting the way a hiring manager "
    "does: you separate what the role actually requires from the prose around it, and "
    "you never add a requirement the posting does not ask for. You quote the posting "
    "verbatim when you say where a requirement came from. You answer with JSON only."
)

# The shape `requirements_from_reply` normalizes and `requirements_failures` grades. Kept
# in the prompt verbatim so the schema and the parser can't drift apart.
SCHEMA = """{
  "requirements": [
    {
      "name": "Kubernetes",
      "kind": "tool",
      "importance": "required",
      "evidence": "Deep Kubernetes experience: you have debugged a CNI, not just applied YAML.",
      "note": ""
    }
  ]
}"""


class JDExtractError(RuntimeError):
    """A requirement list could not be produced. The message says what was wrong.

    `failures` is the validator's sentences, one per thing to fix — the same list the
    repair prompt hands back to the model, and the text a UI shows.
    """

    def __init__(self, message: str, failures: tuple[str, ...] = ()):
        super().__init__(message)
        self.failures = tuple(failures) or (message,)


# --- asking ------------------------------------------------------------------


def build_prompt(doc: dict, *, limit: int = DEFAULT_LIMIT) -> str:
    """The instruction half of the call — the posting is quoted, never interpolated blind."""
    text = str(doc.get("text") or "")[:JD_EXCERPT].strip()
    if not text:
        raise JDExtractError(
            "that job description has no text to extract from — import the posting again"
        )
    title = str(doc.get("title") or jd.DEFAULT_TITLE).strip()
    return f"""Read this job posting and list what it asks a candidate for.

<posting title="{title}">
{text}
</posting>

Return JSON matching exactly this schema, and nothing else:

{SCHEMA}

Rules:
- At most {limit} requirements, ordered as the posting raises them. One requirement per
  thing the posting asks for — split "Strong Go or Python" into two, and do not merge
  two bullets into one entry.
- "name": the skill, tool or competency itself, as the posting names it, with no
  qualifiers ("Kubernetes", not "Deep Kubernetes experience"). Title case for a proper
  name, otherwise a short noun phrase.
- "kind": exactly one of {", ".join(KINDS)} — "tool" for a named technology, language,
  product or platform; "skill" for something the candidate does; "competency" for how
  they work (ownership, incident response, communication).
- "importance": "required" for what the posting asks for outright, "preferred" for
  anything under a nice-to-have, bonus or desirable heading.
- "evidence": the line or phrase of the posting this came from, copied VERBATIM. It is
  checked against the posting, so it must appear there character for character — do not
  paraphrase it, shorten it or fix its wording.
- "note": a short qualifier when the posting gives one ("5+ years", "preferred"); "".
- Extract only what the posting asks for. Salary, location, benefits and the company's
  description of itself are not requirements.
- No prose outside the JSON."""


# --- normalizing what the model sent ----------------------------------------


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _squash(text: str) -> str:
    """Case- and whitespace-insensitive form, for comparing a quote to the posting."""
    return " ".join(str(text or "").casefold().split())


def canonical_kind(value: object) -> str:
    """Map whatever the model called a kind onto one of KINDS, else lower-case it.

    An unmapped kind is kept as written rather than dropped, so the validator can name
    it back to the model instead of silently deciding it was a "skill".
    """
    raw = _text(value).lower().rstrip(".")
    return KIND_ALIASES.get(raw, raw)


def canonical_importance(value: object) -> str:
    """The posting's own required/preferred split. Absent reads as required."""
    raw = _text(value).lower().rstrip(".")
    if not raw:
        return "required"
    return IMPORTANCE_ALIASES.get(raw, raw)


def normalize_requirement(raw: object, index: int) -> dict | None:
    """One requirement in canonical shape, or None when there is nothing there to keep.

    Lenient about what the model names things and about everything it may omit; strict
    about nothing — that is `requirement_failures`, so every complaint is a sentence the
    repair prompt can hand back.
    """
    if not isinstance(raw, dict):
        raise JDExtractError(f"requirement {index} is not an object")
    name = re.sub(r"\s+", " ", _text(raw.get("name") or raw.get("requirement")
                                     or raw.get("title") or raw.get("skill")))
    if not name:
        return None
    return {
        "id": slugify(name, fallback=f"requirement-{index}"),
        "name": name[:MAX_NAME_CHARS],
        "kind": canonical_kind(raw.get("kind") or raw.get("type") or raw.get("category")),
        "importance": canonical_importance(
            raw.get("importance") or raw.get("priority") or raw.get("level")
        ),
        "evidence": re.sub(
            r"\s+", " ",
            _text(raw.get("evidence") or raw.get("span") or raw.get("quote")
                  or raw.get("source")),
        ),
        "note": _text(raw.get("note") or raw.get("qualifier")),
    }


def requirements_from_reply(data: dict) -> list[dict]:
    """Normalize the model's list. Raises only when there is nothing usable in it.

    Two entries for the same thing are one requirement — a posting that says "Terraform"
    twice asks for it once — and the first mention wins, because that is the one whose
    evidence is where the posting raised it.
    """
    if not isinstance(data, dict):
        raise JDExtractError(
            f"the model returned JSON, but not an object (got {type(data).__name__})"
        )
    raw = data.get("requirements")
    if raw is None:
        raw = data.get("items") or data.get("skills")
    if not isinstance(raw, list) or not raw:
        raise JDExtractError("the model returned no requirements")

    requirements: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        requirement = normalize_requirement(item, len(requirements) + 1)
        if requirement is None:
            continue
        key = _squash(requirement["name"])
        if key in seen:
            continue
        seen.add(key)
        requirements.append(requirement)
    if not requirements:
        raise JDExtractError("every requirement the model returned was empty")
    return requirements


def build_requirements(doc: dict, requirements: list[dict], *, model: str = "") -> dict:
    """Assemble the document the gap-analysis band reads. The whole of the format."""
    return {
        "version": REQUIREMENTS_VERSION,
        "jd": str(doc.get("id") or ""),
        "title": str(doc.get("title") or jd.DEFAULT_TITLE),
        "extracted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extracted_by": model,
        "kinds": list(KINDS),
        "count": len(requirements),
        "requirements": requirements,
    }


# --- the strict half ---------------------------------------------------------


def requirement_failures(requirement: object, *, posting: str = "") -> list[str]:
    """What is wrong with one requirement. Empty list == band 76 could consume it.

    `posting` is the canonical JD text; given one, `evidence` has to actually be in it.
    """
    if not isinstance(requirement, dict):
        return ["a requirement is not an object"]
    name = _text(requirement.get("name"))
    where = f"requirement {name!r}" if name else "a requirement"

    failures = []
    if len(name) < MIN_NAME_CHARS:
        failures.append(
            "a requirement has no usable 'name' — name the skill, tool or competency "
            "the posting asks for, on its own and without its qualifiers"
        )
    kind = _text(requirement.get("kind"))
    if kind not in KINDS:
        got = f"{kind!r}" if kind else "nothing"
        failures.append(
            f"{where}: 'kind' is {got}, and it has to be exactly one of "
            f"{', '.join(KINDS)}"
        )
    importance = _text(requirement.get("importance"))
    if importance not in IMPORTANCE:
        got = f"{importance!r}" if importance else "nothing"
        failures.append(
            f"{where}: 'importance' is {got}, and it has to be one of "
            f"{', '.join(IMPORTANCE)}"
        )

    evidence = _text(requirement.get("evidence"))
    if len(evidence) < MIN_EVIDENCE_CHARS:
        failures.append(
            f"{where}: 'evidence' has to quote the line of the posting this came from "
            f"(at least {MIN_EVIDENCE_CHARS} characters), so a reader can check it"
        )
    elif posting and _squash(evidence) not in _squash(posting):
        failures.append(
            f"{where}: 'evidence' does not appear in the posting — {evidence[:80]!r} is "
            "not in it. Quote the posting verbatim, or drop the requirement if the "
            "posting does not actually ask for it"
        )
    return failures


def requirements_failures(doc: object, *, posting: str = "") -> list[str]:
    """The bar a payload must clear before anything downstream may trust it.

    The sentences are the failure text end to end: the repair prompt hands them back to
    the model, `JDExtractError` carries them, and a UI shows them as written.
    """
    if not isinstance(doc, dict):
        return ["the requirements payload does not hold a JSON object"]
    if doc.get("version") != REQUIREMENTS_VERSION:
        return [f"unsupported requirements version {doc.get('version')!r}"]

    requirements = doc.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return ["the posting produced no requirements"]

    failures = []
    for requirement in requirements:
        failures += requirement_failures(requirement, posting=posting)
    return failures


# --- extracting --------------------------------------------------------------


def _clamp(value: object, default: int, high: int) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(n, high))


def extract_requirements(
    doc: dict,
    *,
    client: LLMClient | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Ask the configured model what `doc` requires. Returns the requirements document.

    Pure — it writes nothing. Raises `JDExtractError` when the model's payload does not
    validate (never a partial list) and `LLMError`/`LLMConfigError` when there is no
    model to ask; `client` is injectable so tests and any caller with its own config can
    drive this without touching the network.
    """
    if not isinstance(doc, dict):
        raise JDExtractError("extraction needs an imported job description")
    posting = str(doc.get("text") or "")
    prompt = build_prompt(doc, limit=_clamp(limit, DEFAULT_LIMIT, MAX_LIMIT))

    client = client or LLMClient()
    reply = client.complete(prompt, system=SYSTEM_PROMPT)
    payload = build_requirements(
        doc,
        requirements_from_reply(extract_json(reply)),
        model=getattr(client.config, "model", ""),
    )
    failures = requirements_failures(payload, posting=posting)
    if failures:
        raise JDExtractError(
            "the model's requirement list did not validate: " + "; ".join(failures),
            tuple(failures),
        )
    return payload


def _main(argv: list[str]) -> int:  # pragma: no cover - a convenience CLI
    if "--list" in argv:
        for summary in jd.list_jds():
            print(f"{summary['id']}  {summary.get('words', 0):>5} words  {summary['title']}")
        return 0
    if not argv:
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2
    doc = jd.load_jd(argv[0])
    if doc is None:
        print(f"praxis.jd_extract: no imported job description {argv[0]!r}", file=sys.stderr)
        return 1
    try:
        payload = extract_requirements(doc)
    except (JDExtractError, LLMError, jd.JDError) as exc:
        print(f"praxis.jd_extract: {exc}", file=sys.stderr)
        return 1
    print(f"{payload['title']}  ({payload['count']} requirements)\n")
    for requirement in payload["requirements"]:
        mark = " " if requirement["importance"] == "required" else "~"
        note = f"  ({requirement['note']})" if requirement["note"] else ""
        print(f"  {mark} {requirement['name']:<28} {requirement['kind']:<11}{note}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
