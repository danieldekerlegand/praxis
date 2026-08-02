#!/usr/bin/env python3
"""Reorganize the legacy library and scaffold the new study curriculum.

Two idempotent steps:

  1. reorg()    - move the 7 root notebooks and the 5 legacy notebooks/<section>/
                  folders under notebooks/11-devops-mlops-infra/ (git mv when possible).
  2. scaffold() - for every manifest topic in domains 1-10 (curriculum.py), create a
                  blank study-notebook scaffold if it does not already exist.

Run:  python scaffold_notebooks.py [--no-reorg] [--no-scaffold]

Supersedes generate_notebooks.py / enhance_notebooks.py (kept as legacy).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from curriculum import DOMAINS, NOTEBOOKS_DIR, ROOT, Domain, Topic

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


def scaffold_notebook(domain: Domain, topic: Topic) -> dict:
    runnable = topic.runnable
    note = topic.note or ("conceptual" if not runnable else "")
    tag = "recommended addition" if topic.recommended else "from study list"
    header = (
        f"# {topic.title}\n\n"
        f"> **Study notebook — scaffold.** Replace every TODO and fill to the rubric in "
        f"[`docs/notebook-rubric.md`](../../docs/notebook-rubric.md).\n\n"
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


def scaffold() -> None:
    created = skipped = 0
    for domain in DOMAINS:
        if domain.source != "manifest":
            continue
        (NOTEBOOKS_DIR / domain.dir).mkdir(parents=True, exist_ok=True)
        for topic in domain.topics:
            path = NOTEBOOKS_DIR / domain.dir / f"{topic.slug}.ipynb"
            if path.exists():
                skipped += 1
                continue
            path.write_text(json.dumps(scaffold_notebook(domain, topic), indent=1))
            created += 1
    print(f"scaffold: created {created} new scaffold(s), skipped {skipped} existing.")


def main(argv: list[str]) -> None:
    do_reorg = "--no-reorg" not in argv
    do_scaffold = "--no-scaffold" not in argv
    if do_reorg:
        reorg()
    if do_scaffold:
        scaffold()
    total = sum(1 for _ in NOTEBOOKS_DIR.rglob("*.ipynb"))
    print(f"done. notebooks/ now holds {total} notebook(s).")


if __name__ == "__main__":
    main(sys.argv[1:])
