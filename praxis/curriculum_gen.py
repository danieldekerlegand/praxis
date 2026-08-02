#!/usr/bin/env python3
"""Turn a free-text subject into a structured curriculum.

The user types a goal ("I want to get good at embedded Rust"); this asks the model
configured in praxis/llm.py for modules -> topics, each topic sized to be exactly one
notebook, and normalizes the answer into a `curriculum.Subject`. The result is persisted
under notebooks/subjects/<slug>/curriculum.json for review before anything is scaffolded.

The model is asked for JSON and nothing else, but models still wrap answers in prose or
a fenced block, so `extract_json` is deliberately forgiving. Everything past that point
is strict: `curriculum.subject_from_dict` rejects a payload the scaffolder couldn't use.

CLI:
    python -m praxis.curriculum_gen "quantum computing for programmers"
    python -m praxis.curriculum_gen --modules 6 --topics 5 "conversational French"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import (  # noqa: E402
    CurriculumError,
    Subject,
    save_subject,
    subject_from_dict,
)
from praxis.llm import LLMClient, LLMError  # noqa: E402

DEFAULT_MODULES = 5
DEFAULT_TOPICS_PER_MODULE = 6
MAX_MODULES = 12
MAX_TOPICS_PER_MODULE = 12

SYSTEM_PROMPT = (
    "You are a curriculum architect. You design study curricula that are taught as "
    "Jupyter notebooks: one notebook per topic, each a self-contained refresher a "
    "motivated learner works through in 30-60 minutes. You answer with JSON only."
)

# The shape curriculum.subject_from_dict() normalizes. Kept in the prompt verbatim so the
# schema and the parser can't drift apart.
SCHEMA = """{
  "title": "short title for the subject",
  "blurb": "one sentence on what the learner will be able to do at the end",
  "modules": [
    {
      "title": "module title",
      "blurb": "one sentence on what this module covers",
      "topics": [
        {
          "title": "topic title — one notebook",
          "slug": "kebab-case-file-stem",
          "runnable": true,
          "note": ""
        }
      ]
    }
  ]
}"""


def build_prompt(goal: str, modules: int, topics_per_module: int) -> str:
    """The instruction half of the call — the goal is quoted, never interpolated blind."""
    return f"""Design a study curriculum for this learner goal:

<goal>
{goal.strip()}
</goal>

Return JSON matching exactly this schema, and nothing else:

{SCHEMA}

Rules:
- About {modules} modules, ordered so each builds on the ones before it.
- About {topics_per_module} topics per module. Every topic is ONE notebook: narrow
  enough to teach properly, substantial enough to be worth its own file.
- Every notebook is filled to a fixed rubric (what & why, mental model, key concepts,
  setup, at least two worked examples, gotchas, alternatives, resources), so pick topics
  that can actually carry worked examples.
- "runnable": true when the topic can be demonstrated with executable Python in a
  notebook; false when it can't (another language, a GUI/SaaS product, a hardware or
  paper-and-pencil topic) and the notebook must lean on CLI commands, snippets or
  diagrams instead.
- "note": a short qualifier when one matters ("needs API key", "R kernel", "needs
  hardware"); otherwise "".
- "slug": kebab-case, unique across the whole curriculum, safe as a filename.
- Titles are specific: "Ownership and Borrowing", not "Rust Basics part 2".
- No prose outside the JSON."""


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, fenced block or prose notwithstanding."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        body = raw.split("```")
        raw = body[1] if len(body) > 1 else raw
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise CurriculumError(f"no JSON object in the model's reply: {text[:200]!r}")
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError as exc:
        raise CurriculumError(f"the model's reply was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CurriculumError("the model returned JSON, but not an object")
    return data


def _clamp(value: object, default: int, high: int) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(n, high))


def generate_curriculum(
    goal: str,
    *,
    client: LLMClient | None = None,
    modules: int = DEFAULT_MODULES,
    topics_per_module: int = DEFAULT_TOPICS_PER_MODULE,
    slug: str = "",
) -> Subject:
    """Ask the configured model for a curriculum for `goal`. Raises CurriculumError.

    `client` is injectable so tests (and any caller with its own config) can drive this
    without touching the network; by default it is built from the environment.
    """
    goal = (goal or "").strip()
    if not goal:
        raise CurriculumError("a subject needs a goal — say what you want to learn")

    client = client or LLMClient()
    prompt = build_prompt(
        goal,
        _clamp(modules, DEFAULT_MODULES, MAX_MODULES),
        _clamp(topics_per_module, DEFAULT_TOPICS_PER_MODULE, MAX_TOPICS_PER_MODULE),
    )
    reply = client.complete(prompt, system=SYSTEM_PROMPT)
    return subject_from_dict(
        extract_json(reply), slug=slug, goal=goal, model=client.config.model
    )


def generate_and_save(goal: str, **kwargs) -> Subject:
    """Generate a curriculum and persist it for review. Returns the subject."""
    subject = generate_curriculum(goal, **kwargs)
    save_subject(subject)
    return subject


def _main(argv: list[str]) -> int:
    modules, topics, words = DEFAULT_MODULES, DEFAULT_TOPICS_PER_MODULE, []
    it = iter(argv)
    for arg in it:
        if arg == "--modules":
            modules = _clamp(next(it, None), DEFAULT_MODULES, MAX_MODULES)
        elif arg == "--topics":
            topics = _clamp(next(it, None), DEFAULT_TOPICS_PER_MODULE, MAX_TOPICS_PER_MODULE)
        else:
            words.append(arg)
    goal = " ".join(words)
    if not goal:
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2
    try:
        subject = generate_and_save(goal, modules=modules, topics_per_module=topics)
    except (CurriculumError, LLMError) as exc:
        print(f"praxis.curriculum_gen: {exc}", file=sys.stderr)
        return 1
    print(f"{subject.title}  ({subject.n_topics} topics) -> {subject.path}")
    for module in subject.modules:
        print(f"\n  {module.title}")
        for topic in module.topics:
            mark = " " if topic.runnable else "~"
            print(f"    {mark} {topic.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
