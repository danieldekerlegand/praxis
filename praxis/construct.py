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

A constructed notebook is then given the knowledge checks that gate it
(`praxis.checks.generate_checks`, written beside it as `<slug>.checks.json`). Same two
invariants — a set that isn't gradable is never written, an existing one is skipped —
so a topic whose notebook is already ✅ but has no checks yet gains them on a re-run.

CLI:
    python -m praxis.construct notebooks/subjects/rust/01-basics/ownership.ipynb
    python -m praxis.construct --force <path>      # rebuild an already-complete notebook
    python -m praxis.construct --no-checks <path>  # notebook only, no knowledge checks
    python -m praxis.construct --execute <path>    # also run it through nbconvert
    python -m praxis.construct --subject rust      # the whole curriculum, resumably
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import (  # noqa: E402
    DOMAINS,
    NOTEBOOKS_DIR,
    CurriculumError,
    Domain,
    Subject,
    Topic,
    all_subjects,
    domain_path,
    load_subject,
    topic_path,
)
from nbstatus import notebook_meta, status_from_dict  # noqa: E402
from praxis.checks import ChecksResult, generate_checks  # noqa: E402
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
    # The knowledge checks written beside the notebook (praxis/checks.py), or None when
    # the run was told to skip them / never got a notebook worth checking.
    checks: ChecksResult | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("constructed", "skipped")

    @property
    def checks_ok(self) -> bool:
        """Whether this topic can be gated — no checks asked for counts as fine."""
        return self.checks is None or self.checks.ok

    def summary(self) -> str:
        mark = {"constructed": "✅", "skipped": "•", "failed": "⚠️"}[self.status]
        tail = f" — {self.detail or '; '.join(self.failures)}" if self.status == "failed" else ""
        checks = f"  ·  {self.checks.count} checks {self.checks.status}" if self.checks else ""
        return f"{mark} {self.title} ({self.status}, {self.chars} chars){checks}{tail}"


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
    checks: bool = True,
) -> ConstructionResult:
    """Fill one topic's notebook to the rubric. Never writes content that fails the gate.

    A tutorial is not finished when its prose is: unless `checks=False`, the notebook is
    followed by the knowledge checks that gate it (praxis/checks.py), written beside it.
    Both halves are idempotent, so a resumed run generates only what is missing.

    Returns a ConstructionResult rather than raising, so a batch run can carry on past
    a topic the model kept getting wrong (a raise here would strand the rest).
    """
    path = topic_path(domain, topic)
    existing = _read_notebook(path) if path.is_file() else None
    if existing is not None and not force and status_from_dict(existing)[0] == "complete":
        return _with_checks(
            ConstructionResult(
                path=path, slug=topic.slug, title=topic.title, status="skipped",
                chars=len(notebook_text(existing)), detail="already complete",
            ),
            domain, topic, existing, enabled=checks, client=client, subject=subject,
            attempts=attempts, force=force, write=write,
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
            return _with_checks(
                ConstructionResult(
                    path=path, slug=topic.slug, title=topic.title, status="constructed",
                    attempts=used, chars=len(notebook_text(nb)),
                ),
                domain, topic, nb, enabled=checks, client=client, subject=subject,
                attempts=attempts, force=force, write=write,
            )

    return ConstructionResult(
        path=path, slug=topic.slug, title=topic.title, status="failed",
        attempts=used, chars=len(notebook_text(nb)) if nb else 0,
        failures=tuple(failures), detail=detail,
    )


def _with_checks(
    result: ConstructionResult,
    domain: Domain,
    topic: Topic,
    nb: dict,
    *,
    enabled: bool,
    **kwargs,
) -> ConstructionResult:
    """Attach the topic's knowledge checks to a notebook that passed the gate.

    Reported alongside the notebook rather than folded into it: the notebook on disk is
    genuinely complete either way, and a set of checks the model could not make gradable
    must not un-write it. `result.checks_ok` is the "this tutorial can be gated" half.
    """
    if not enabled:
        return result
    return replace(result, checks=generate_checks(domain, topic, notebook=nb, **kwargs))


# --- constructing many ------------------------------------------------------


class _LazyClient:
    """An LLMClient built on first use, so a batch of already-✅ topics needs no key.

    One client for a whole run (the config is resolved once), but resolving it is
    deferred: re-running a finished curriculum to confirm it is done must not fail
    because nothing is configured to call.
    """

    def __init__(self) -> None:
        self._client: LLMClient | None = None

    def _get(self) -> LLMClient:
        if self._client is None:
            self._client = LLMClient()
        return self._client

    @property
    def config(self):
        return self._get().config

    def complete(self, prompt: str, **kwargs) -> str:
        return self._get().complete(prompt, **kwargs)


# One target of a batch: the topic, the module it belongs to, and its curriculum.
Target = tuple[Domain, Topic, Subject | None]

# What a batch reports as it goes: the topic it is starting, then its result. The
# result carries a slug, not a module, so its module comes back alongside it.
OnStart = Callable[[Domain, Topic], None]
OnResult = Callable[[ConstructionResult, Domain], None]


def construct_each(
    targets: list[Target],
    *,
    client: LLMClient | None = None,
    on_start: OnStart | None = None,
    on_result: OnResult | None = None,
    **kwargs,
) -> list[ConstructionResult]:
    """Construct a list of targets in order — the one batch loop in Praxis.

    Resumable by construction: every target goes through `construct_topic`, so one that
    is already ✅ is skipped rather than rewritten, and a topic the model kept getting
    wrong comes back as a "failed" result instead of stranding the rest of the batch.
    One client is shared across the run and resolved only if some topic actually needs
    it, so re-running a finished curriculum needs no key at all.
    """
    client = client or _LazyClient()
    results = []
    for domain, topic, subject in targets:
        if on_start:
            on_start(domain, topic)
        result = construct_topic(domain, topic, client=client, subject=subject, **kwargs)
        results.append(result)
        if on_result:
            on_result(result, domain)
    return results


def construct_domain(
    domain: Domain,
    *,
    subject: Subject | None = None,
    topics: list[Topic] | None = None,
    **kwargs,
) -> list[ConstructionResult]:
    """Construct one module/domain, in curriculum order.

    `topics` overrides which ones — a `filesystem` domain enumerates none, so its
    caller passes what it found on disk.
    """
    chosen = list(domain.topics) if topics is None else topics
    return construct_each([(domain, t, subject) for t in chosen], **kwargs)


def construct_subject(subject: Subject, **kwargs) -> list[ConstructionResult]:
    """Construct a whole curriculum, module by module. Same skip-if-✅ resumability."""
    return construct_each(
        [(m, t, subject) for m in subject.modules for t in m.topics], **kwargs
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
    parent = path.parent
    domain = next((d for d in DOMAINS if domain_path(d).resolve() == parent), None)
    if domain is None:
        # Deeper than any manifest domain (domain 11 nests). The synthesized domain is
        # the file's own directory, so topic_path() lands back on this exact file.
        root = NOTEBOOKS_DIR.resolve()
        domain = Domain(
            dir=(parent.relative_to(root).as_posix() if root in parent.parents
                 else meta.get("domain", "")),
            title=parent.name.replace("-", " ").title(),
            blurb="",
            source="filesystem",
        )
    title = meta.get("title") or path.stem.replace("-", " ").title()
    return domain, Topic(
        slug=path.stem, title=title,
        runnable=bool(meta.get("runnable", True)),
        recommended=bool(meta.get("recommended", False)),
        note=str(meta.get("note", "")),
    ), None


def topic_for_rel(rel: str) -> tuple[Domain, Topic, Subject | None]:
    """Resolve a library `rel` — the `<domain.dir>/<slug>.ipynb` the UI holds.

    Goes through the curriculum rather than the filesystem, because a generated
    subject's `Domain.dir` is *not* where the file sits when `PRAXIS_SUBJECTS_DIR`
    has moved it (`domain_path()` owns that translation).
    """
    rel = str(rel).strip("/")
    if not rel or ".." in Path(rel).parts:
        raise CurriculumError(f"not a library path: {rel!r}")
    dir_part, _, name = rel.rpartition("/")
    slug = name[: -len(".ipynb")] if name.endswith(".ipynb") else name
    for subject in all_subjects():
        for module in subject.modules:
            if module.dir != dir_part:
                continue
            for topic in module.topics:
                if topic.slug == slug:
                    return module, topic, subject
            return topic_for_path(domain_path(module) / name)  # scaffolded, off-manifest
    return topic_for_path(NOTEBOOKS_DIR / rel)


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
    checks = "--no-checks" not in argv
    subject_slug = ""
    if "--subject" in argv:
        i = argv.index("--subject")
        subject_slug = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    paths = [a for a in argv if not a.startswith("-")]
    if not paths and not subject_slug:
        print(__doc__.strip().split("CLI:")[-1].strip(), file=sys.stderr)
        return 2

    failed = 0
    results: list[ConstructionResult] = []
    if subject_slug:
        try:
            results = construct_subject(load_subject(subject_slug), force=force,
                                        checks=checks)
        except CurriculumError as exc:
            print(f"praxis.construct: {exc}", file=sys.stderr)
            return 1

    for raw in paths:
        try:
            results.append(construct_path(raw, force=force, checks=checks))
        except CurriculumError as exc:
            print(f"praxis.construct: {exc}", file=sys.stderr)
            failed += 1

    for result in results:
        print(result.summary())
        for failure in result.failures:
            print(f"    - {failure}", file=sys.stderr)
        if not result.checks_ok:
            for failure in result.checks.failures or (result.checks.detail,):
                print(f"    - checks: {failure}", file=sys.stderr)
            failed += 1
        if not result.ok:
            failed += 1
        elif execute and result.status == "constructed":
            ok, message = execute_notebook(result.path)
            print(f"    execute: {message}", file=sys.stderr if not ok else sys.stdout)
            failed += 0 if ok else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
