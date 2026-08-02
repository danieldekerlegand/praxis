/**
 * User-defined subjects, as the launcher's `/api/subjects` serves them.
 *
 * These types mirror `Subject.to_dict()` in curriculum.py one-for-one. Defining a
 * subject is the one call in this app that writes: it spends tokens against the user's
 * own key (praxis/llm.py) and persists the curriculum for review before scaffolding.
 */

export type SubjectTopic = {
  slug: string;
  title: string;
  /** False when the topic can't be driven from Python — CLI/snippets/diagrams instead. */
  runnable: boolean;
  recommended: boolean;
  note: string;
};

export type SubjectModule = {
  /** Path under notebooks/, e.g. `subjects/embedded-rust/01-foundations`. */
  dir: string;
  title: string;
  blurb: string;
  topics: SubjectTopic[];
};

export type Subject = {
  slug: string;
  title: string;
  /** The free text the user typed. */
  goal: string;
  blurb: string;
  /** ISO-8601 UTC. */
  created: string;
  /** Which model wrote this curriculum. */
  model: string;
  source: "generated" | "seed";
  n_topics: number;
  modules: SubjectModule[];
};

/** The launcher reports why a definition failed; surface its message, not the status. */
async function fail(res: Response, what: string): Promise<never> {
  let detail = `${res.status}`;
  try {
    const body = (await res.json()) as { error?: string };
    if (body?.error) detail = body.error;
  } catch {
    /* no JSON body — the status is all we have */
  }
  throw new Error(`${what}: ${detail}`);
}

export async function fetchSubjects(base: string): Promise<Subject[]> {
  const res = await fetch(`${base}/api/subjects`);
  if (!res.ok) return fail(res, "could not list subjects");
  return ((await res.json()) as { subjects: Subject[] }).subjects;
}

export type DefineOptions = {
  modules?: number;
  topicsPerModule?: number;
};

/** Generate + persist a curriculum for a free-text goal. Slow: it calls the model. */
export async function defineSubject(
  base: string,
  goal: string,
  options: DefineOptions = {},
): Promise<Subject> {
  const res = await fetch(`${base}/api/subjects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      goal,
      modules: options.modules ?? 5,
      topics_per_module: options.topicsPerModule ?? 6,
    }),
  });
  if (!res.ok) return fail(res, "could not generate a curriculum");
  return (await res.json()) as Subject;
}
