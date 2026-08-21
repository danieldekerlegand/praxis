import { fail } from "./subjects";

export type SuggestionRequirement = {
  id: string;
  name: string;
  kind: string;
  importance: string;
  evidence: string;
  note: string;
};

export type Suggestion = {
  id: string;
  title: string;
  goal: string;
  coverage: string;
  rationale: string;
  requirement: SuggestionRequirement;
  evidence: Array<Record<string, unknown>>;
};

export type SuggestionReview = {
  jd: string;
  title: string;
  count: number;
  suggestions: Suggestion[];
  dropped: Suggestion[];
  accepted: Array<{ id: string; slug: string }>;
};

export async function fetchSuggestions(base: string, jdId: string): Promise<SuggestionReview> {
  const res = await fetch(`${base}/api/jd/${encodeURIComponent(jdId)}/suggestions`);
  if (!res.ok) return fail(res, "could not load suggestions");
  return (await res.json()) as SuggestionReview;
}

export async function editSuggestion(
  base: string,
  jdId: string,
  id: string,
  goal: string,
): Promise<SuggestionReview> {
  const res = await fetch(
    `${base}/api/jd/${encodeURIComponent(jdId)}/suggestions/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ goal }),
    },
  );
  if (!res.ok) return fail(res, "could not edit suggestion");
  return (await res.json()) as SuggestionReview;
}

export async function dropSuggestion(
  base: string,
  jdId: string,
  id: string,
): Promise<SuggestionReview> {
  const res = await fetch(
    `${base}/api/jd/${encodeURIComponent(jdId)}/suggestions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!res.ok) return fail(res, "could not drop suggestion");
  return (await res.json()) as SuggestionReview;
}

export async function acceptSuggestion(
  base: string,
  jdId: string,
  id: string,
): Promise<{ slug: string; suggestion: Suggestion }> {
  const res = await fetch(
    `${base}/api/jd/${encodeURIComponent(jdId)}/suggestions/${encodeURIComponent(id)}/accept`,
    { method: "POST" },
  );
  if (!res.ok) return fail(res, "could not accept suggestion");
  return (await res.json()) as { slug: string; suggestion: Suggestion };
}
