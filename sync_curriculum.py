#!/usr/bin/env python3
"""Sync the filesystem and Ralph tasklists to curriculum.py after topics are removed.

Idempotent. For manifest domains it:
  - deletes notebook files whose slug is no longer in curriculum.py
  - deletes whole notebooks/<dir>/ and ralph/<dir>/ for domains dropped entirely
  - prunes each ralph/<dir>/tasks.json and prd.json, dropping entries whose notebook
    no longer exists WHILE PRESERVING the `completed` flags / story ids of survivors
The legacy filesystem domain (11) is never pruned. Run generate_docs.py afterwards.

Run:  python sync_curriculum.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from curriculum import DOMAINS, NOTEBOOKS_DIR, ROOT

RALPH_DIR = ROOT / "ralph"
NB_RE = re.compile(r"(notebooks/[^\s`;]+\.ipynb)")

MANIFEST_DIRS = {d.dir for d in DOMAINS if d.source == "manifest"}
LEGACY_DIRS = {d.dir for d in DOMAINS if d.source == "filesystem"}
EXPECTED = {d.dir: {t.slug for t in d.topics} for d in DOMAINS if d.source == "manifest"}

DRY = "--dry-run" in sys.argv
log: list[str] = []


def _git(*args) -> bool:
    try:
        subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def remove(path: Path) -> None:
    rel = path.relative_to(ROOT)
    log.append(f"  delete {rel}")
    if DRY:
        return
    if path.is_dir():
        if not _git("rm", "-r", "-q", str(rel)):
            shutil.rmtree(path, ignore_errors=True)
    else:
        if not _git("rm", "-q", str(rel)):
            path.unlink(missing_ok=True)


def prune_notebooks() -> int:
    removed = 0
    for d in sorted(NOTEBOOKS_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if name in LEGACY_DIRS:
            continue
        if name not in MANIFEST_DIRS:  # whole domain dropped (e.g. 06)
            log.append(f"domain dropped: notebooks/{name}/")
            for _ in d.rglob("*.ipynb"):
                removed += 1
            remove(d)
            continue
        keep = EXPECTED[name]
        for nb in sorted(d.glob("*.ipynb")):
            if nb.stem not in keep:
                remove(nb)
                removed += 1
    return removed


def _surviving(items: list, key_path) -> list:
    out = []
    for it in items:
        text = key_path(it)
        m = NB_RE.search(text or "")
        if not m:
            out.append(it)  # no path -> keep (be conservative)
            continue
        if (ROOT / m.group(1)).exists():
            out.append(it)
    return out


def prune_tasklists() -> int:
    dropped = 0
    for sub in sorted(RALPH_DIR.iterdir()):
        if not sub.is_dir():
            continue
        name = sub.name
        if name not in MANIFEST_DIRS and name not in LEGACY_DIRS:
            log.append(f"domain dropped: ralph/{name}/")
            tj = sub / "tasks.json"
            if tj.exists():
                dropped += len(json.loads(tj.read_text()).get("tasks", []))
            remove(sub)
            continue

        tj, pj = sub / "tasks.json", sub / "prd.json"
        if tj.exists():
            data = json.loads(tj.read_text())
            before = data.get("tasks", [])
            after = _surviving(before, lambda t: t.get("description", ""))
            if len(after) != len(before):
                dropped += len(before) - len(after)
                done = sum(1 for t in after if t.get("completed"))
                log.append(f"  ralph/{name}/tasks.json: {len(before)} -> {len(after)} "
                           f"({done} completed preserved)")
                data["tasks"] = after
                if not DRY:
                    tj.write_text(json.dumps(data, indent=2) + "\n")
        if pj.exists():
            data = json.loads(pj.read_text())
            before = data.get("userStories", [])
            after = _surviving(before, lambda s: s.get("notes", ""))
            if len(after) != len(before):
                data["userStories"] = after
                if not DRY:
                    pj.write_text(json.dumps(data, indent=2) + "\n")
    return dropped


def main() -> None:
    print(f"Syncing filesystem + tasklists to curriculum.py{' (dry run)' if DRY else ''}\n")
    nb = prune_notebooks()
    tasks = prune_tasklists()
    print("\n".join(log) if log else "  nothing to remove.")
    print(f"\nRemoved {nb} notebook(s); dropped {tasks} task(s).")
    if not DRY:
        print("Next: python generate_docs.py  (and update ralph/run.sh TASKLISTS if a domain was dropped)")


if __name__ == "__main__":
    main()
