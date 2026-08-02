/**
 * Studying a gated tutorial — the learner's side of the app.
 *
 * These types mirror `study_model()` in launcher/app.py one-for-one. Nothing here
 * decides what is unlocked: the launcher derives that from the outcomes it recorded and
 * serves it on every request, and a locked section arrives with `checks: []` — the
 * questions themselves never cross the wire until the learner has earned them. Posting
 * an answer at a locked check comes back 423, so the gate is the server's, not a
 * disabled button's.
 */

import type { Status } from "./library";
import { fail } from "./subjects";

export type Kind = "choice" | "code" | "short";

/** One graded answer, kept verbatim — the record of what the learner actually wrote. */
export type Outcome = {
  check_id: string;
  kind: Kind;
  section: string;
  passed: boolean;
  answer: string;
  detail: string;
  /** "auto" for choice/code; the model's name for a short answer. */
  graded_by: string;
  graded: string;
};

/** A check as the learner may see it: no `answer`, no `solution`, no marking key. */
export type Check = {
  id: string;
  section: string;
  kind: Kind;
  prompt: string;
  /** choice only. */
  options?: string[];
  /** code only — the stub to start from. */
  starter?: string;
  answered: boolean;
  passed: boolean;
  outcome: Outcome | null;
  /** Given away only once the check has been graded. */
  explanation: string;
};

export type Section = {
  section: string;
  locked: boolean;
  complete: boolean;
  passed: number;
  n: number;
  /** Empty while the section is locked — the questions are withheld, not just hidden. */
  checks: Check[];
};

export type Study = {
  rel: string;
  title: string;
  domain: string;
  learner: string;
  status: Status;
  /** True while an earlier topic in this module is unfinished. */
  locked: boolean;
  /** The title of that topic. */
  blockedBy: string;
  sections: Section[];
  /** False when nothing was ever generated to gate this notebook. */
  gated: boolean;
  passed: number;
  n: number;
  complete: boolean;
  unlocked: string[];
  /** The section to work on now, "" when there is none left. */
  next: string;
};

export type Answer = { outcome: Outcome; state: Study };

export async function fetchStudy(base: string, rel: string, learner = ""): Promise<Study> {
  const query = learner ? `?learner=${encodeURIComponent(learner)}` : "";
  const res = await fetch(`${base}/api/study/${rel}${query}`);
  if (!res.ok) return fail(res, "could not open this tutorial");
  return (await res.json()) as Study;
}

/**
 * Submit one answer. The launcher grades it, records it, and hands back the gate as it
 * now stands — so the view is never guessing what the answer unlocked.
 */
export async function submitAnswer(
  base: string,
  rel: string,
  checkId: string,
  answer: string,
  learner = "",
): Promise<Answer> {
  const query = learner ? `?learner=${encodeURIComponent(learner)}` : "";
  const res = await fetch(`${base}/api/study/${rel}${query}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ check_id: checkId, answer }),
  });
  if (!res.ok) return fail(res, "that answer could not be graded");
  return (await res.json()) as Answer;
}

/** What a section's header says about it. */
export function sectionMark(section: Section): string {
  if (section.locked) return "🔒";
  return section.complete ? "✅" : "○";
}

/** One line of "where am I", under the topic title. */
export function studySummary(study: Study): string {
  if (!study.gated) return "This tutorial has no knowledge checks yet — build it to gate it.";
  if (study.locked) return `Locked — finish ${study.blockedBy || "the previous topic"} first.`;
  if (study.complete) return `Passed — ${study.passed}/${study.n} checks.`;
  return `${study.passed}/${study.n} checks passed · next up: ${study.next}`;
}
