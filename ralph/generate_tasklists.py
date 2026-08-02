#!/usr/bin/env python3
"""Emit one ralphy tasklist per domain from curriculum.py.

For each domain NN-<slug> writes ralph/NN-<slug>/:
  - prd.json   human-readable user stories (one per notebook below the rubric bar)
  - tasks.json ralphy-executable {project, description, tasks:[{title, description, completed}]}

A notebook becomes a task only if it's not already complete (status != "complete"),
so re-generating after a fill run naturally shrinks the tasklists. Each task embeds
the full rubric + per-topic context, so a fresh ralphy agent needs nothing else.

Run:  python ralph/generate_tasklists.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import DOMAINS, NOTEBOOKS_DIR, Domain  # noqa: E402
from nbstatus import notebook_status  # noqa: E402

RALPH_DIR = ROOT / "ralph"

RUBRIC = (
    "Bring this notebook to the completion rubric in docs/notebook-rubric.md. "
    "Keep the 8 sections (What & Why; Mental Model; Key Concepts; Setup; Worked "
    "Examples; Gotchas & Pitfalls; When to Use vs Alternatives; Resources). "
    "Remove every TODO/placeholder. Write a real, concise refresher with the right "
    "depth for someone who knew this once and is reloading it."
)

RUNNABLE_RULE = (
    "This topic IS Python-runnable: include >= 2 executed code cells that run "
    "top-to-bottom in a fresh kernel with real output; prefer tiny CPU-friendly "
    "examples; gate any API-key/large-download cell behind an os.getenv check so the "
    "notebook still executes. When done, set metadata.praxis.status to \"complete\"."
)
CONCEPTUAL_RULE = (
    "This topic is NOT Python-runnable in a notebook ({note}): use CLI commands, "
    "config/code snippets, and pseudo-code, and say so explicitly — no fake print() "
    "theater. When done, set metadata.praxis.status to \"complete\"."
)

LEGACY_RULE = (
    "This is a legacy DevOps/MLOps notebook from the original library. Replace all "
    "template placeholder text with real, accurate content in its existing section "
    "structure; add concrete commands/manifests/code where useful. It does not need "
    "the 8-section study format, but it must contain no placeholder text and be a "
    "substantive, correct reference."
)

ACCEPTANCE = (
    "Acceptance criteria (all must be met before marking complete):\n"
    "- No placeholder/TODO text remains anywhere in the notebook\n"
    "- The notebook is valid nbformat and opens in JupyterLab\n"
    "- Content is accurate and genuinely useful as a refresher\n"
    "- tests/test_notebooks.py passes for this notebook\n"
    "- The launcher shows this notebook as ✅ complete"
)


def _ctx(domain: Domain) -> str:
    return (
        f"Project context: Praxis tutorial notebook library. This task belongs to domain "
        f"'{domain.title}' (notebooks/{domain.dir}/). Single source of truth is curriculum.py; "
        f"the rubric is docs/notebook-rubric.md; the gate is tests/test_notebooks.py. Edit only "
        f"the one notebook for this task. After editing, run `python generate_docs.py` is NOT "
        f"required (CURRICULUM.md is regenerated separately)."
    )


def _new_curriculum_rows(domain: Domain):
    """(slug, title, rel, runnable, note, recommended) for incomplete manifest notebooks."""
    base = NOTEBOOKS_DIR / domain.dir
    rows = []
    for t in domain.topics:
        p = base / f"{t.slug}.ipynb"
        status = notebook_status(p)[0] if p.exists() else "scaffold"
        if status == "complete":
            continue
        rows.append((t.slug, t.title, p.relative_to(ROOT).as_posix(),
                     t.runnable, t.note, t.recommended))
    return rows


def _legacy_rows(domain: Domain):
    base = NOTEBOOKS_DIR / domain.dir
    rows = []
    for p in sorted(base.rglob("*.ipynb")):
        if notebook_status(p)[0] == "complete":
            continue
        title = p.stem.replace("-", " ").title()
        rows.append((p.stem, title, p.relative_to(ROOT).as_posix(), p.parent.name))
    return rows


def build_domain(domain: Domain, index: int) -> tuple[dict, dict]:
    short = domain.dir.split("-", 1)[1]
    desc = f"{domain.title} — {domain.blurb}"
    stories, tasks = [], []

    if domain.source == "filesystem":
        rows = _legacy_rows(domain)
        for prio, (slug, title, rel, section) in enumerate(rows, 1):
            tid = f"T{index}-{prio:03d}"
            body = (
                f"Complete the study notebook `{rel}` ({title}; legacy section: {section}).\n\n"
                f"{LEGACY_RULE}\n\n{ACCEPTANCE}\n\n{_ctx(domain)}"
            )
            stories.append({
                "id": tid, "title": f"Complete: {title}",
                "description": f"Finish the legacy notebook for {title}.",
                "acceptanceCriteria": ACCEPTANCE.splitlines()[1:],
                "priority": prio, "passes": False, "notes": f"file: {rel}",
            })
            tasks.append({"title": f"{tid}: Complete {title}",
                          "description": body, "completed": False})
    else:
        rows = _new_curriculum_rows(domain)
        for prio, (slug, title, rel, runnable, note, recommended) in enumerate(rows, 1):
            tid = f"T{index}-{prio:03d}"
            rule = RUNNABLE_RULE if runnable else CONCEPTUAL_RULE.format(note=note or "see curriculum.py")
            rec = " (recommended addition, not in the original study list)" if recommended else ""
            body = (
                f"Complete the study notebook `{rel}` for **{title}**{rec}.\n\n"
                f"{RUBRIC}\n\n{rule}\n\n{ACCEPTANCE}\n\n{_ctx(domain)}"
            )
            stories.append({
                "id": tid, "title": f"Complete: {title}",
                "description": f"Write the {title} refresher to the rubric.",
                "acceptanceCriteria": ACCEPTANCE.splitlines()[1:],
                "priority": prio, "passes": False,
                "notes": f"file: {rel}; runnable: {runnable}; recommended: {recommended}",
            })
            tasks.append({"title": f"{tid}: Complete {title}",
                          "description": body, "completed": False})

    prd = {
        "project": "praxis",
        "branchName": f"ralph/{short}",
        "description": desc,
        "userStories": stories,
    }
    tasklist = {
        "project": "praxis",
        "description": desc,
        "tasks": tasks,
    }
    return prd, tasklist


def main() -> None:
    summary = []
    for i, domain in enumerate(DOMAINS, 1):
        prd, tasklist = build_domain(domain, i)
        out = RALPH_DIR / domain.dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "prd.json").write_text(json.dumps(prd, indent=2) + "\n")
        (out / "tasks.json").write_text(json.dumps(tasklist, indent=2) + "\n")
        summary.append((domain.dir, len(tasklist["tasks"])))
    total = sum(n for _, n in summary)
    print(f"Generated {len(summary)} tasklists, {total} tasks total:")
    for d, n in summary:
        print(f"  ralph/{d:42} {n:3} tasks")


if __name__ == "__main__":
    main()
