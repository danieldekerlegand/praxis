/**
 * Construction — the third write, after defining a subject and scaffolding it.
 *
 * Filling a notebook to the rubric is a model call per notebook, so the launcher
 * answers `POST /api/construct` with a *job* (launcher/jobs.py) and this polls it while
 * the badges move 🔴 → ⏳ → ✅. Nothing here decides what "complete" means: every phase
 * and badge in a job comes from the Python grader and nbstatus, read back off the file
 * the constructor actually wrote.
 */

import { useEffect, useRef, useState } from "react";
import type { Status } from "./library";
import { fail } from "./subjects";

/** Per-notebook phase: two of the job's own, then the three ConstructionResult ones. */
export type Phase = "pending" | "building" | "constructed" | "skipped" | "failed";

export type JobItem = {
  /** Path under notebooks/ — the same `rel` /api/library serves. */
  rel: string;
  slug: string;
  title: string;
  phase: Phase;
  /** Live nbstatus badge for the file, "" when there is no notebook yet. */
  badge: Status | "";
  attempts: number;
  chars: number;
  /** Why the grader refused the model's draft (nothing was written). */
  failures: string[];
  detail: string;
};

export type Job = {
  id: string;
  kind: "topic" | "module" | "subject";
  /** What was asked for: a rel, a module dir, or a subject slug. */
  target: string;
  title: string;
  state: "running" | "done";
  force: boolean;
  /** Set only when the run itself broke — a refused notebook is an item failure. */
  error: string;
  started: string;
  finished: string;
  n: number;
  done: number;
  constructed: number;
  skipped: number;
  failed: number;
  /** Title of the notebook being written right now. */
  current: string;
  items: JobItem[];
};

/** Construct one notebook, one module, or a whole curriculum. */
export type ConstructTarget =
  | { rel: string }
  | { domain: string }
  | { subject: string };

export async function startConstruction(
  base: string,
  target: ConstructTarget,
  force = false,
): Promise<Job> {
  const res = await fetch(`${base}/api/construct`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...target, force }),
  });
  if (!res.ok) return fail(res, "could not start construction");
  return (await res.json()) as Job;
}

export async function fetchJob(base: string, id: string): Promise<Job> {
  const res = await fetch(`${base}/api/construct/${encodeURIComponent(id)}`);
  if (!res.ok) return fail(res, "lost track of the construction");
  return (await res.json()) as Job;
}

/**
 * The run in flight right now, if any.
 *
 * A construction outlives the view that started it — the window can be reopened, or the
 * run started from the "define a subject" tab — and the launcher owns it either way, so
 * the shell asks who is running rather than assuming nobody is.
 */
export async function fetchRunning(base: string): Promise<Job | null> {
  const res = await fetch(`${base}/api/construct`);
  if (!res.ok) return fail(res, "could not list constructions");
  const body = (await res.json()) as { running: string | null; jobs: Job[] };
  return body.jobs.find((j) => j.id === body.running) ?? null;
}

/** How often to ask how it is going — a notebook takes tens of seconds. */
const POLL_MS = 900;

/** What `useConstruction` hands back — one run, shared by every view that shows it. */
export type Construction = {
  job: Job | null;
  error: string | null;
  start: (target: ConstructTarget, force?: boolean) => Promise<void>;
  running: boolean;
};

/**
 * Drive the shell's one construction run: start it, then poll until it is done.
 *
 * Held once, at the top of the app, and passed down — a run started from "define a
 * subject" is the same run the library watches, and only one poller asks. On mount it
 * adopts whatever the launcher already has in flight, so reopening the window rejoins
 * a run in progress instead of showing a stale library.
 *
 * `onSettled` fires once the run finishes, which is where the caller reloads the
 * library so the authoritative badges replace the job's.
 */
export function useConstruction(base: string, onSettled?: () => void): Construction {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const settled = useRef(onSettled);
  settled.current = onSettled;

  const runningId = job?.state === "running" ? job.id : null;

  // Adopt a run already in flight (started before this view mounted) and poll it too.
  useEffect(() => {
    if (!base) return;
    let live = true;
    fetchRunning(base)
      .then((running) => {
        if (live && running) setJob((prev) => prev ?? running);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [base]);

  useEffect(() => {
    if (!runningId) return;
    let live = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const next = await fetchJob(base, runningId);
        if (!live) return;
        setJob(next);
        if (next.state === "done") {
          settled.current?.();
          return;
        }
      } catch (err) {
        if (live) setError(err instanceof Error ? err.message : String(err));
        return;
      }
      timer = window.setTimeout(tick, POLL_MS);
    };
    timer = window.setTimeout(tick, POLL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [base, runningId]);

  async function start(target: ConstructTarget, force = false) {
    if (runningId) return;
    setError(null);
    try {
      setJob(await startConstruction(base, target, force));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return { job, error, start, running: Boolean(runningId) };
}

/** The job's view of one notebook, if this run touches it. */
export function itemFor(job: Job | null, rel: string): JobItem | undefined {
  return job?.items.find((i) => i.rel === rel);
}

/**
 * What to show next to a topic: the job's phase while it is being written, and
 * otherwise the badge nbstatus gives the file on disk.
 */
export function phaseBadge(
  item: JobItem | undefined,
  badges: Record<string, string>,
  fallback: Status,
): string {
  if (!item || item.phase === "pending") return badges[fallback] ?? "";
  if (item.phase === "building") return "⏳";
  if (item.phase === "failed") return badges.error ?? "⚠️";
  return badges[item.badge || fallback] ?? "";
}

/** One line of "how is it going" — what the shell shows under the run. */
export function jobSummary(job: Job): string {
  if (job.state === "running") {
    return job.current
      ? `writing ${job.current} — ${job.done}/${job.n} done`
      : `starting on ${job.n} notebook${job.n === 1 ? "" : "s"}…`;
  }
  const parts = [`${job.constructed} constructed`];
  if (job.skipped) parts.push(`${job.skipped} already complete`);
  if (job.failed) parts.push(`${job.failed} refused by the gate`);
  return `${job.title}: ${parts.join(" · ")}`;
}
