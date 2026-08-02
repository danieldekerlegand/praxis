#!/usr/bin/env python3
"""Construction jobs — the one long-running write in the launcher.

Defining a subject and scaffolding it both answer inside a request. Construction does
not: filling a curriculum is one model call per notebook, minutes of work, and the point
of the UI is watching the 🔴 → 🟡 → ✅ transitions happen. So a construction request
starts a background thread and returns a job the shell polls (`GET /api/construct/<id>`).

What this module owns is *bookkeeping only*. Every decision about content stays in
praxis/construct.py: what to write, what already passes, and — the invariant this must
not weaken — that a notebook failing the grader is never written. A job reports the
`ConstructionResult` it got; it never marks an item complete on its own say-so, and the
badge it shows for a finished item is re-read from nbstatus, off the file on disk.

One job runs at a time (`registry.running()`), so two clicks can't have two threads
filling the same notebook.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import Domain, Topic, domain_path  # noqa: E402
from nbstatus import notebook_status  # noqa: E402
from praxis import construct  # noqa: E402

# Per-item phases. "pending"/"building" are the job's own; the other three are exactly
# the ConstructionResult statuses, so nothing is invented here.
PENDING, BUILDING = "pending", "building"

# How many finished jobs stay queryable — enough for the shell to re-read the last run.
KEEP_JOBS = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def topic_rel(domain: Domain, topic: Topic) -> str:
    """The library `rel` for a topic — the same string /api/library serves."""
    return f"{domain.dir}/{topic.slug}.ipynb"


@dataclass
class JobItem:
    """One notebook in a job: where it is, and what the constructor made of it."""

    rel: str
    slug: str
    title: str
    phase: str = PENDING
    badge: str = ""          # live nbstatus status, re-read after the constructor ran
    attempts: int = 0
    chars: int = 0
    failures: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "rel": self.rel,
            "slug": self.slug,
            "title": self.title,
            "phase": self.phase,
            "badge": self.badge,
            "attempts": self.attempts,
            "chars": self.chars,
            "failures": list(self.failures),
            "detail": self.detail,
        }


@dataclass
class Job:
    """A construction run over one topic, one module, or a whole subject."""

    id: str
    kind: str                # "topic" | "module" | "subject"
    target: str              # the rel / domain dir / subject slug that was asked for
    title: str
    items: list[JobItem]
    force: bool = False
    state: str = "running"   # "running" | "done"
    error: str = ""          # set only when the run itself broke (not a failed notebook)
    started: str = field(default_factory=_now)
    finished: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _find(self, rel: str) -> JobItem | None:
        return next((i for i in self.items if i.rel == rel), None)

    def start_item(self, domain: Domain, topic: Topic) -> None:
        with self._lock:
            item = self._find(topic_rel(domain, topic))
            if item:
                item.phase = BUILDING

    def finish_item(self, result: construct.ConstructionResult, domain: Domain) -> None:
        """Record a result. The badge is read back off the file, never assumed."""
        rel = f"{domain.dir}/{result.slug}.ipynb"
        status, _ = notebook_status(result.path)
        with self._lock:
            item = self._find(rel)
            if item is None:
                return
            item.phase = result.status
            item.badge = status
            item.attempts = result.attempts
            item.chars = result.chars
            item.failures = result.failures
            item.detail = result.detail

    def finish(self, error: str = "") -> None:
        with self._lock:
            self.error = error
            self.state = "done"
            self.finished = _now()
            for item in self.items:  # nothing stays mid-flight once the thread is gone
                if item.phase == BUILDING:
                    item.phase, item.detail = "failed", error or item.detail

    def to_dict(self) -> dict:
        with self._lock:
            items = [i.to_dict() for i in self.items]
        counts = {phase: sum(1 for i in items if i["phase"] == phase)
                  for phase in (PENDING, BUILDING, "constructed", "skipped", "failed")}
        current = next((i["title"] for i in items if i["phase"] == BUILDING), "")
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "title": self.title,
            "state": self.state,
            "force": self.force,
            "error": self.error,
            "started": self.started,
            "finished": self.finished,
            "n": len(items),
            "done": len(items) - counts[PENDING] - counts[BUILDING],
            "constructed": counts["constructed"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "current": current,
            "items": items,
        }


def badge_for(domain: Domain, topic: Topic) -> str:
    """The topic's badge right now — "" when there is no notebook yet to badge."""
    status, _ = notebook_status(domain_path(domain) / f"{topic.slug}.ipynb")
    return "" if status == "error" else status


class JobRegistry:
    """The launcher's in-process job table. One construction runs at a time."""

    def __init__(self, keep: int = KEEP_JOBS):
        self._jobs: list[Job] = []
        self._keep = keep
        self._lock = threading.Lock()
        self._n = 0

    # -- queries ---------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.id == job_id), None)

    def running(self) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.state == "running"), None)

    def recent(self) -> list[Job]:
        with self._lock:
            return list(reversed(self._jobs))

    # -- starting --------------------------------------------------------

    def _add(self, job: Job) -> Job:
        with self._lock:
            self._jobs.append(job)
            if len(self._jobs) > self._keep:  # forget old jobs, never a live one
                recent = self._jobs[-self._keep:]
                older = [j for j in self._jobs[:-self._keep] if j.state == "running"]
                self._jobs = older + recent
        return job

    def _next_id(self, kind: str) -> str:
        with self._lock:
            self._n += 1
            return f"{kind}-{self._n}"

    def start(self, kind: str, target: str, title: str,
              targets: list[construct.Target], *, client=None, force=False) -> Job:
        """Start a run over `targets` — one topic, a module's worth, or a whole subject.

        The caller resolves what to build (the launcher knows the library); this only
        watches `praxis.construct` do it.
        """
        job = self._add(Job(
            id=self._next_id(kind), kind=kind, target=target, title=title,
            items=[JobItem(rel=topic_rel(d, t), slug=t.slug, title=t.title,
                           badge=badge_for(d, t)) for d, t, _ in targets],
            force=force,
        ))

        def run() -> None:
            construct.construct_each(
                targets, client=client, force=force,
                on_start=job.start_item, on_result=job.finish_item,
            )

        def body() -> None:
            try:
                run()
            except Exception as exc:  # a broken run must still close the job
                job.finish(f"{type(exc).__name__}: {exc}")
            else:
                job.finish()

        threading.Thread(target=body, name=f"praxis-{job.id}", daemon=True).start()
        return job
