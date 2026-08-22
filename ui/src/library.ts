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
  /** How many are gated for real — key *and* released graded cells (praxis/coverage.py). */
  covered: number;
};

/** One domain's line of the coverage report — the primary figure, per praxis/coverage.py. */
export type DomainCoverage = {
  dir: string;
  name: string;
  title: string;
  gated: number;
  total: number;
  complete: number;
  pct: number;
};

/**
 * How much of the library actually gates, as `praxis.coverage.coverage_report` computes
 * it off these very rows. Rendered, never recomputed here: the overall fraction is the
 * sum of the per-domain ones on the launcher's side, so the shell cannot show a number
 * the gate does not enforce.
 */
export type Coverage = {
  domains: DomainCoverage[];
  gated: number;
  total: number;
  complete: number;
  pct: number;
  /** Breadth — how many domains have any gate at all. That is what a backfill moves. */
  domainsGated: number;
  domainsTotal: number;
};

export type Library = {
  domains: Domain[];
  counts: Record<Status, number>;
  total: number;
  /** status -> emoji, straight from nbstatus.BADGE. */
  badge: Record<Status, string>;
  lab_base: string;
  pct: number;
  /** Gated coverage, folded onto the library so a backfill's progress needs no second poll. */
  coverage: Coverage;
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
