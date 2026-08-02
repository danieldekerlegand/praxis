/**
 * The seed library, as the launcher's `/api/library` serves it.
 *
 * These types mirror `build_model()` in launcher/app.py one-for-one — the shell renders
 * that model rather than recomputing anything, so badges here and in the standalone
 * launcher UI can never drift apart.
 */

export type Status = "scaffold" | "partial" | "complete" | "error";

export type Topic = {
  title: string;
  /** Path under notebooks/, e.g. `01-symbolic-ai-logic/datalog.ipynb`. */
  rel: string;
  status: Status;
  recommended: boolean;
  note: string;
  /** True once knowledge checks have been written beside this notebook. */
  gated: boolean;
  /** Every one of them passed. */
  complete: boolean;
  passed: number;
  checks: number;
  /** Locked while an earlier topic in the same module is unfinished. */
  locked: boolean;
  /** The title of that topic. */
  blockedBy: string;
};

export type Domain = {
  dir: string;
  name: string;
  title: string;
  blurb: string;
  topics: Topic[];
  /** Topic count, and how many of them are ✅ complete. */
  n: number;
  done: number;
  /** How many carry knowledge checks, and how many the learner has passed. */
  gated: number;
  passed: number;
};

export type Library = {
  domains: Domain[];
  counts: Record<Status, number>;
  total: number;
  /** status -> emoji, straight from nbstatus.BADGE. */
  badge: Record<Status, string>;
  lab_base: string;
  pct: number;
};

export async function fetchLibrary(base: string): Promise<Library> {
  const res = await fetch(`${base}/api/library`);
  if (!res.ok) {
    throw new Error(`GET ${base}/api/library -> ${res.status}`);
  }
  return (await res.json()) as Library;
}

/** Read-only HTML render of one notebook — what the reader pane iframes. */
export function renderUrl(base: string, rel: string): string {
  return `${base}/render/${rel}`;
}

/** The same notebook, live and editable, in JupyterLab (needs `praxis-lab` running). */
export function labUrl(library: Library, rel: string): string {
  return `${library.lab_base}/lab/tree/notebooks/${rel}`;
}
