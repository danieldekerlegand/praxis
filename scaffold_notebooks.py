#!/usr/bin/env python3
"""Scaffold rubric-shaped notebooks for any curriculum — seed or user-defined.

A scaffold is a valid notebook carrying the 8 sections of docs/notebook-rubric.md with
every section still a TODO, and `metadata.praxis.status = "scaffold"` so nbstatus.py
badges it 🔴 and tests/test_notebooks.py skips grading it until an author fills it.

Two idempotent steps:

  1. reorg()    - move the 7 root notebooks and the 5 legacy notebooks/<section>/
                  folders under notebooks/11-devops-mlops-infra/ (git mv when possible).
  2. scaffold() - write a scaffold for every topic that has no notebook yet, across the
                  seed manifest (curriculum.py domains 1-10) AND every user-defined
                  subject persisted under notebooks/subjects/ (see praxis/curriculum_gen).

Both kinds of curriculum are `Domain`/`Topic` objects, so scaffolding needs no branch for
a generated subject — only `domain_path()` differs, which resolves a subject's modules
under `subjects_dir()`. Nothing here ever rewrites an existing file: a topic whose
notebook exists is skipped, so re-scaffolding a partly-filled curriculum only fills gaps.

Run:  python scaffold_notebooks.py [--no-reorg] [--no-scaffold] [--no-subjects]
      python scaffold_notebooks.py --subject <slug>     # just one defined subject

Supersedes generate_notebooks.py / enhance_notebooks.py (kept as legacy).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from curriculum import (
    DOMAINS,
    NOTEBOOKS_DIR,
    ROOT,
    CurriculumError,
    Domain,
    Subject,
    Topic,
    all_subjects,
    domain_path,
    load_subject,
    topic_path,
)

LEGACY_DOMAIN = "11-devops-mlops-infra"
LEGACY_ROOT_NOTEBOOKS = [
    "bedrock.ipynb",
    "efa.ipynb",
    "ena.ipynb",
    "karpenter-cluster-autoscaler.ipynb",
    "models.ipynb",
    "sagemaker.ipynb",
    "storage-csi-drivers.ipynb",
]
LEGACY_SECTION_DIRS = [
    "distributed-training-tools",
    "job-orchestration-tools",
    "model-serving-libraries",
    "nvidia-gpu-components",
    "techniques",
]


def _git_mv(src: Path, dst: Path) -> None:
    """git mv when the repo tracks src; otherwise a plain filesystem move."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "mv", str(src), str(dst)],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.move(str(src), str(dst))


def reorg() -> None:
    dest = NOTEBOOKS_DIR / LEGACY_DOMAIN
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0

    for name in LEGACY_ROOT_NOTEBOOKS:
        src = ROOT / name
        dst = dest / name
        if src.exists() and not dst.exists():
            _git_mv(src, dst)
            moved += 1

    for section in LEGACY_SECTION_DIRS:
        src = NOTEBOOKS_DIR / section
        dst = dest / section
        if src.exists() and not dst.exists():
            _git_mv(src, dst)
            moved += 1

    print(f"reorg: moved {moved} item(s) into notebooks/{LEGACY_DOMAIN}/")


def _rubric_link(domain: Domain) -> str:
    """A link to the rubric that resolves from inside notebooks/<domain.dir>/.

    A seed domain sits one level under notebooks/ (`../../`); a generated subject's
    module sits three (`subjects/<slug>/<NN-module>/`), so the depth is computed rather
    than assumed — a dead link in every scaffold is a rubric nobody reads.
    """
    return "../" * (len(domain.dir.strip("/").split("/")) + 1) + "docs/notebook-rubric.md"


def scaffold_notebook(domain: Domain, topic: Topic) -> dict:
    runnable = topic.runnable
    note = topic.note or ("conceptual" if not runnable else "")
    tag = "recommended addition" if topic.recommended else "from study list"
    header = (
        f"# {topic.title}\n\n"
        f"> **Study notebook — scaffold.** Replace every TODO and fill to the rubric in "
        f"[`docs/notebook-rubric.md`]({_rubric_link(domain)}).\n\n"
        f"**Domain:** {domain.title}  ·  **{tag}**  ·  "
        f"**runnable:** {'yes' if runnable else 'no — conceptual / CLI / snippets'}"
        + (f"  ·  _{note}_" if note else "")
    )

    counter = {"n": 0}

    def _cid() -> str:
        counter["n"] += 1
        return f"{topic.slug}-{counter['n']:02d}"

    def md(text: str) -> dict:
        return {"cell_type": "markdown", "id": _cid(), "metadata": {}, "source": [text]}

    def code(text: str) -> dict:
        return {"cell_type": "code", "id": _cid(), "execution_count": None,
                "metadata": {}, "outputs": [], "source": [text]}

    cells = [
        md(header),
        md("## 1. What & Why\n\nTODO: what it is, the problem it solves, and when to reach for it."),
        md("## 2. Mental Model\n\nTODO: the one diagram/analogy that makes it click."),
        md("## 3. Key Concepts\n\nTODO: the handful of terms/ideas you must know."),
        md("## 4. Setup\n\nTODO: install/prereqs."),
    ]
    if runnable:
        cells.append(code(f"# TODO: setup / install\n# %pip install ...\nprint('TODO: {topic.title}')"))
        cells.append(md("## 5. Worked Examples\n\nTODO: at least two runnable examples with output."))
        cells.append(code("# TODO: worked example 1"))
        cells.append(code("# TODO: worked example 2"))
    else:
        cells.append(md(
            "## 5. Worked Examples\n\nTODO: at least two concrete walkthroughs. "
            "This topic isn't Python-runnable in a notebook — use CLI commands, config/code "
            "snippets, screenshots, or pseudo-code, and say so explicitly."))
    cells += [
        md("## 6. Gotchas & Pitfalls\n\nTODO: the mistakes that bite people."),
        md("## 7. When to Use vs Alternatives\n\nTODO: trade-offs and the competing options."),
        md("## 8. Resources\n\nTODO: official docs + 2-3 high-signal links (real URLs)."),
    ]

    return {
        "cells": cells,
        "metadata": {
            "praxis": {
                "status": "scaffold",
                "domain": domain.dir,
                "slug": topic.slug,
                "runnable": runnable,
                "recommended": topic.recommended,
                "note": topic.note,
            },
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def scaffold_domain(domain: Domain) -> tuple[int, int]:
    """Scaffold every topic of one domain. Returns (created, skipped).

    Works on a seed domain and on a generated subject's module alike — `domain_path`
    knows where each one's notebooks live. An existing notebook is skipped, never
    rewritten, which is what makes re-scaffolding safe once an author has filled some.
    """
    if domain.source == "filesystem":
        return 0, 0  # the legacy library: topics ARE the files, nothing to scaffold
    created = skipped = 0
    base = domain_path(domain)
    base.mkdir(parents=True, exist_ok=True)
    for topic in domain.topics:
        path = topic_path(domain, topic)
        if path.exists():
            skipped += 1
            continue
        path.write_text(json.dumps(scaffold_notebook(domain, topic), indent=1))
        created += 1
    return created, skipped


def scaffold_subject(subject: Subject) -> tuple[int, int]:
    """Scaffold a whole curriculum — one notebook per topic. Returns (created, skipped)."""
    created = skipped = 0
    for module in subject.modules:
        c, s = scaffold_domain(module)
        created, skipped = created + c, skipped + s
    return created, skipped


def scaffold(subjects: bool = True) -> tuple[int, int]:
    """The seed manifest, plus every user-defined subject unless told otherwise."""
    created = skipped = 0
    for domain in DOMAINS:
        c, s = scaffold_domain(domain)
        created, skipped = created + c, skipped + s
    if subjects:
        for subject in all_subjects():
            c, s = scaffold_subject(subject)
            created, skipped = created + c, skipped + s
    print(f"scaffold: created {created} new scaffold(s), skipped {skipped} existing.")
    return created, skipped


def main(argv: list[str]) -> int:
    slug = ""
    if "--subject" in argv:
        i = argv.index("--subject")
        slug = argv[i + 1] if i + 1 < len(argv) else ""
        if not slug:
            print("--subject needs a subject slug", file=sys.stderr)
            return 2

    if slug:
        # One defined subject, on its own: no reorg, no seed sweep.
        try:
            subject = load_subject(slug)
        except CurriculumError as exc:
            print(f"scaffold_notebooks: {exc}", file=sys.stderr)
            return 1
        created, skipped = scaffold_subject(subject)
        print(f"scaffold: {subject.title} -> created {created}, skipped {skipped} "
              f"existing, in {subject.dir}")
        return 0

    if "--no-reorg" not in argv:
        reorg()
    if "--no-scaffold" not in argv:
        scaffold(subjects="--no-subjects" not in argv)
    total = sum(1 for _ in NOTEBOOKS_DIR.rglob("*.ipynb"))
    print(f"done. notebooks/ now holds {total} notebook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
