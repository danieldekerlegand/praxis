#!/usr/bin/env python3
"""Fill a scaffolded notebook to the rubric with the configured model.

This is the headline capability: the scaffolder writes the eight empty sections
(scaffold_notebooks.py), and this writes what goes in them — explanations, worked
examples, and for a runnable topic, code cells that actually run.

The loop is generate -> grade -> repair, and the grader is the gate itself
(`praxis.rubric.construction_failures`, which is tests/test_notebooks.py's rules plus
the ✅ badge, real resource URLs, and code that parses). Two consequences worth being
explicit about, because they are the anti-fabrication contract:

  - **A notebook that fails the grader is never written.** The scaffold stays on disk
    untouched and the failures come back to the caller. Nothing is ever flipped to
    `status: "complete"` on unfilled content.
  - **A notebook that is already ✅ is skipped, not rewritten** (`force=True` overrides),
    so re-running across a curriculum resumes rather than clobbering an author's work —
    the same idempotence rule the scaffolder follows.

Like praxis/curriculum_gen.py the model is asked for JSON and nothing else, the client
is injectable so tests never touch the network, and everything past the parse is strict.

CLI:
    python -m praxis.construct notebooks/subjects/rust/01-basics/ownership.ipynb
    python -m praxis.construct --force <path>      # rebuild an already-complete notebook
    python -m praxis.construct --execute <path>    # also run it through nbconvert
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import (  # noqa: E402
    DOMAINS,
    CurriculumError,
    Domain,
    Subject,
    Topic,
    all_subjects,
    domain_path,
    topic_path,
)
from nbstatus import notebook_meta, status_from_dict  # noqa: E402
from praxis.curriculum_gen import extract_json  # noqa: E402
from praxis.llm import LLMClient, LLMError  # noqa: E402
from praxis.rubric import construction_failures, notebook_text  # noqa: E402

DEFAULT_ATTEMPTS = 3

# Above nbstatus.py's 6000-char ✅ threshold on purpose: asking for the floor gets the
# floor, and a notebook that lands one paragraph short wastes a whole repair round.
TARGET_CHARS = 9000

SYSTEM_PROMPT = (
    "You are a senior engineer-educator writing study notebooks for a smart colleague "
    "who needs a refresher, not a beginner who needs hand-holding. You are concrete, "
    "opinionated where it helps, and you never pad. Every fact you state is one you are "
    "confident is true; every URL you give is one that really exists. You answer with "
    "JSON only."
)

CELL_SCHEMA = """{
  "cells": [
    {"type": "markdown", "source": "## 1. What & Why\\n\\n..."},
    {"type": "code", "source": "import math\\nprint(math.pi)"}
  ]
}"""


class ConstructionError(RuntimeError):
    """The notebook could not be constructed to the rubric."""


@dataclass(frozen=True)
class ConstructionResult:
    """What one construction attempt did — the shape the batch runner and UI report."""

    path: Path
    slug: str
    title: str
    status: str  # "constructed" | "skipped" | "failed"
    attempts: int = 0
    chars: int = 0
    failures: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("constructed", "skipped")

    def summary(self) -> str:
        mark = {"constructed": "✅", "skipped": "•", "failed": "⚠️"}[self.status]
        tail = f" — {self.detail or '; '.join(self.failures)}" if self.status == "failed" else ""
        return f"{mark} {self.title} ({self.status}, {self.chars} chars){tail}"


# --- the prompt -------------------------------------------------------------


def _runnable_rules(topic: Topic) -> str:
    if topic.runnable:
        return (
            "- This topic IS Python-runnable. Include at least THREE code cells that run "
            "top-to-bottom in a fresh kernel: one under Setup and one per worked example.\n"
            "- Code must be correct as written and self-contained: tiny data, CPU-only, no "
            "large downloads. Prefer the standard library; when a third-party package is "
            "genuinely needed, open Setup with a real `%pip install <package>` line.\n"
            "- Anything needing a key or the network goes behind an "
            "`if os.getenv(\"SOME_KEY\"):` check, with the call shape still shown, so the "
            "notebook executes either way.\n"
            "- Print real, small outputs. Never fake output in a comment."
        )
    return (
        "- This topic is NOT Python-runnable, so emit NO code cells at all. Teach with "
        "fenced blocks inside markdown: CLI commands, config files, snippets in the "
        "topic's real language, or pseudo-code.\n"
        "- Say plainly, in one line near the top, that it isn't runnable from a Python "
        "notebook and why. No `print()` theatre pretending otherwise."
    )


def build_prompt(domain: Domain, topic: Topic, *, subject: Subject | None = None) -> str:
    """The instruction half of the call. Context is quoted, never interpolated blind."""
    siblings = [t.title for t in domain.topics if t.slug != topic.slug][:12]
    context = [f"Module / domain: {domain.title}"]
    if domain.blurb:
        context.append(f"Module blurb: {domain.blurb}")
    if subject:
        context.append(f"Curriculum: {subject.title}")
        if subject.goal:
            context.append(f"The learner's goal: {subject.goal}")
    if siblings:
        context.append(
            "Other notebooks in this module (cross-link instead of duplicating them): "
            + ", ".join(siblings)
        )
    if topic.note:
        context.append(f"Note on this topic: {topic.note}")

    return f"""Write the complete study notebook for this topic:

<topic>
{topic.title}
</topic>

<context>
{chr(10).join(context)}
</context>

Return JSON matching exactly this schema, and nothing else:

{CELL_SCHEMA}

Structure — these eight markdown sections, in this order, with these exact headings:

1. `## 1. What & Why` — what it is, the problem it solves, when to reach for it and when not to.
2. `## 2. Mental Model` — the single analogy or diagram that makes it click.
3. `## 3. Key Concepts` — the handful of terms you must hold in your head.
4. `## 4. Setup` — install and prerequisites.
5. `## 5. Worked Examples` — AT LEAST TWO concrete examples, each introduced by its own
   `### Example N: <what it shows>` markdown cell.
6. `## 6. Gotchas & Pitfalls` — the mistakes that actually bite people, not generic advice.
7. `## 7. When to Use vs Alternatives` — honest trade-offs against the real competitors,
   named. A short markdown table works well here.
8. `## 8. Resources` — the official docs plus at least three high-signal links, each a
   real, complete `https://` URL you are confident exists. No bare `[Link]`, no
   example.com, no invented deep links — link the project's real docs or repo root if
   you are unsure of a sub-page.

{_runnable_rules(topic)}

Rules:
- Do NOT write a title cell — the first cell is `## 1. What & Why`. The header is added
  for you.
- The words "TODO", "add code here" and "provide description here" must appear nowhere.
  Every section is finished prose, not a note to a future author.
- Around {TARGET_CHARS} characters of content in total, and never under 6000. Depth, not padding.
- Markdown "source" is one string per cell with real newlines escaped as \\n.
- No prose outside the JSON."""


def _repair_prompt(prompt: str, previous: dict, failures: list[str]) -> str:
    """Hand the model its own draft and the grader's complaints, ask for a full redo."""
    draft = "\n\n---\n\n".join(
        f"[{c.get('cell_type')}]\n{''.join(c.get('source', ''))}"
        for c in previous.get("cells", [])
    )[:24000]
    return (
        f"{prompt}\n\n"
        "Your previous draft FAILED the automated completion gate:\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n\nHere is that draft:\n\n<draft>\n"
        + draft
        + "\n</draft>\n\nReturn the COMPLETE corrected notebook as JSON in the same "
        "schema — every cell, not a patch, and fix every failure listed above."
    )


# --- model reply -> notebook ------------------------------------------------


def _header_cell(domain: Domain, topic: Topic) -> str:
    """The title block. Deliberately free of the scaffold's marker text."""
    kind = "runnable" if topic.runnable else "conceptual — not Python-runnable"
    note = f"  ·  _{topic.note}_" if topic.note else ""
    return f"# {topic.title}\n\n**{domain.title}**  ·  {kind}{note}"


def cells_from_reply(data: dict) -> list[dict]:
    """Normalize the model's cell list. Lenient about shape, strict about content."""
    raw = data.get("cells")
    if not isinstance(raw, list) or not raw:
        raise ConstructionError("the model returned no cells")
    cells = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ConstructionError(f"cell {i} is not an object")
        kind = str(item.get("type") or item.get("cell_type") or "markdown").strip().lower()
        if kind not in ("markdown", "code"):
            kind = "markdown"
        source = item.get("source", "")
        if isinstance(source, list):
            source = "".join(str(s) for s in source)
        source = str(source).strip("\n")
        if not source.strip():
            continue  # an empty cell teaches nothing; drop it rather than fail the batch
        cells.append({"kind": kind, "source": source})
    if not cells:
        raise ConstructionError("every cell the model returned was empty")
    return cells


def build_notebook(
    domain: Domain,
    topic: Topic,
    cells: list[dict],
    *,
    model: str = "",
    scaffold: dict | None = None,
) -> dict:
    """Assemble the notebook: our header, the model's cells, the scaffold's metadata."""
    counter = {"n": 0}

    def _cid() -> str:
        counter["n"] += 1
        return f"{topic.slug}-{counter['n']:02d}"

    def cell(kind: str, source: str) -> dict:
        base = {"cell_type": kind, "id": _cid(), "metadata": {}, "source": [source]}
        if kind == "code":
            base |= {"execution_count": None, "outputs": []}
        return base

    body = [cell("markdown", _header_cell(domain, topic))]
    body += [cell(c["kind"], c["source"]) for c in cells]

    praxis_meta = dict(notebook_meta(scaffold or {}))
    praxis_meta |= {
        "status": "complete",
        "domain": domain.dir,
        "slug": topic.slug,
        "runnable": topic.runnable,
        "recommended": topic.recommended,
        "note": topic.note,
        "constructed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "constructed_by": model,
    }
    meta = dict((scaffold or {}).get("metadata", {}))
    meta.pop("ai_tutor", None)  # collapse the legacy key onto the current one
    meta |= {
        "praxis": praxis_meta,
        "kernelspec": meta.get("kernelspec")
        or {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": meta.get("language_info") or {"name": "python"},
    }
    return {"cells": body, "metadata": meta, "nbformat": 4, "nbformat_minor": 5}


# --- constructing one notebook ---------------------------------------------


def _read_notebook(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def construct_topic(
    domain: Domain,
    topic: Topic,
    *,
    client: LLMClient | None = None,
    subject: Subject | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    force: bool = False,
    write: bool = True,
) -> ConstructionResult:
    """Fill one topic's notebook to the rubric. Never writes content that fails the gate.

    Returns a ConstructionResult rather than raising, so a batch run can carry on past
    a topic the model kept getting wrong (a raise here would strand the rest).
    """
    path = topic_path(domain, topic)
    existing = _read_notebook(path) if path.is_file() else None
    if existing is not None and not force and status_from_dict(existing)[0] == "complete":
        return ConstructionResult(
            path=path, slug=topic.slug, title=topic.title, status="skipped",
            chars=len(notebook_text(existing)), detail="already complete",
        )

    client = client or LLMClient()
    prompt = build_prompt(domain, topic, subject=subject)
    failures: list[str] = ["no attempt was made"]
    detail = ""
    nb: dict | None = None
    used = 0

    for used in range(1, max(1, attempts) + 1):
        ask = prompt if nb is None else _repair_prompt(prompt, nb, failures)
        try:
            reply = client.complete(ask, system=SYSTEM_PROMPT)
            nb = build_notebook(
                domain, topic, cells_from_reply(extract_json(reply)),
                model=getattr(client.config, "model", ""), scaffold=existing,
            )
        except (LLMError, CurriculumError, ConstructionError) as exc:
            failures, detail, nb = [str(exc)], str(exc), None
            continue
        failures = construction_failures(nb)
        if not failures:
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(nb, indent=1))
            return ConstructionResult(
                path=path, slug=topic.slug, title=topic.title, status="constructed",
                attempts=used, chars=len(notebook_text(nb)),
            )

    return ConstructionResult(
        path=path, slug=topic.slug, title=topic.title, status="failed",
        attempts=used, chars=len(notebook_text(nb)) if nb else 0,
        failures=tuple(failures), detail=detail,
    )


# --- finding the topic behind a path ---------------------------------------


def topic_for_path(path: str | Path) -> tuple[Domain, Topic, Subject | None]:
    """Resolve a notebook path back to its curriculum entry (seed domain or subject)."""
    path = Path(path).resolve()
    for subject in all_subjects():
        for module in subject.modules:
            for topic in module.topics:
                if topic_path(module, topic).resolve() == path:
                    return module, topic, subject
    for domain in DOMAINS:
        for topic in domain.topics:
            if topic_path(domain, topic).resolve() == path:
                return domain, topic, None
    # A legacy/filesystem notebook has no manifest entry; synthesize one from its metadata
    # so the constructor still works on domain 11.
    nb = _read_notebook(path)
    if nb is None:
        raise CurriculumError(f"no notebook at {path}")
    meta = notebook_meta(nb)
    domain = next(
        (d for d in DOMAINS if domain_path(d).resolve() in path.parents),
        Domain(dir=meta.get("domain", ""), title=path.parent.name, blurb=""),
    )
    title = meta.get("title") or path.stem.replace("-", " ").title()
    return domain, Topic(
        slug=path.stem, title=title,
        runnable=bool(meta.get("runnable", True)),
        recommended=bool(meta.get("recommended", False)),
        note=str(meta.get("note", "")),
    ), None


def construct_path(path: str | Path, **kwargs) -> ConstructionResult:
    """Construct the notebook at `path`, whichever curriculum it belongs to."""
    domain, topic, subject = topic_for_path(path)
    return construct_topic(domain, topic, subject=subject, **kwargs)


# --- optional: prove the code really runs -----------------------------------


def execute_notebook(path: str | Path, timeout: int = 600) -> tuple[bool, str]:
    """Run a notebook with nbconvert, in place. (ok, message).

    The rubric lets CI skip this when a heavy optional dependency is missing, so a
    missing jupyter is reported as a skip, not a failure — but a notebook that errors
    when jupyter IS present is a real failure.
    """
    path = Path(path)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
             "--execute", "--inplace", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return True, "skipped: jupyter not installed"
    except subprocess.TimeoutExpired:
        return False, f"execution timed out after {timeout}s"
    if proc.returncode == 0:
        return True, "executed cleanly"
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-8:]
    if any("No module named jupyter" in line for line in tail):
        return True, "skipped: jupyter not installed"
    return False, "\n".join(tail)


# --- CLI --------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    force = "--force" in argv
    execute = "--execute" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2

    failed = 0
    for raw in paths:
        try:
            result = construct_path(raw, force=force)
        except CurriculumError as exc:
            print(f"praxis.construct: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(result.summary())
        for failure in result.failures:
            print(f"    - {failure}", file=sys.stderr)
        if not result.ok:
            failed += 1
        elif execute and result.status == "constructed":
            ok, message = execute_notebook(result.path)
            print(f"    execute: {message}", file=sys.stderr if not ok else sys.stdout)
            failed += 0 if ok else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
