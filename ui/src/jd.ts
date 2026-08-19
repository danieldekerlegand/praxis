/**
 * Imported job descriptions, as the launcher's `/api/jd` serves them.
 *
 * These types mirror the canonical document `praxis/jd.py` writes one-for-one. This is
 * the one document the user *brings* rather than types a goal for, and importing it
 * spends no tokens: normalizing a posting to plain text needs no model, so this whole
 * path works with no key configured.
 *
 * Two ways in, one document out. A paste is JSON; a file is sent as the **raw request
 * body** with its name in the query string rather than as multipart — a `File` is
 * already a `BodyInit`, so this is a shorter fetch here and one less dependency on the
 * launcher's side.
 */

/** One posting in the list — `praxis.jd.list_jds` drops `text`, so this has no `text`. */
export type JDSummary = {
  /** `<title-slug>-<digest of the text>` — re-importing the same posting reuses it. */
  id: string;
  title: string;
  /** How it arrived. */
  source: "paste" | "upload";
  /** `text` · `markdown` · `pdf` · `docx` — what had to be parsed to get the text. */
  kind: string;
  mime: string;
  /** The uploaded file's name; empty for a paste. */
  filename: string;
  chars: number;
  words: number;
  /** ISO-8601 UTC. */
  created: string;
  version: number;
};

/** One posting, with the canonical plain text every later band reads. */
export type JD = JDSummary & { text: string };

/** The launcher reports why a write failed; surface its message, not the status. */
async function fail(res: Response, what: string): Promise<never> {
  const body = await res.json().catch(() => null);
  throw new Error((body as { error?: string } | null)?.error || `${what}: ${res.status}`);
}

export async function fetchJDs(base: string): Promise<JDSummary[]> {
  const res = await fetch(`${base}/api/jd`);
  if (!res.ok) return fail(res, "could not list job descriptions");
  return ((await res.json()) as { jds: JDSummary[] }).jds;
}

/** One posting including its text — what the confirmation view reads back. */
export async function fetchJD(base: string, id: string): Promise<JD> {
  const res = await fetch(`${base}/api/jd/${encodeURIComponent(id)}`);
  if (!res.ok) return fail(res, "could not read that job description");
  return (await res.json()) as JD;
}

/**
 * Import a pasted posting. Rejects with the launcher's own sentence — an empty paste or
 * one too short to be a posting is refused server-side and nothing is written.
 */
export async function importJDText(base: string, text: string, title = ""): Promise<JD> {
  const res = await fetch(`${base}/api/jd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!res.ok) return fail(res, "could not import that job description");
  return (await res.json()) as JD;
}

/**
 * Import a picked file — `.txt` / `.md` / `.pdf` / `.docx`, parsed down to plain text.
 *
 * The bytes go up as the body verbatim; the launcher decides what is readable, so an
 * unsupported format or a scan with no extractable text comes back as a thrown `Error`
 * carrying what to do instead.
 */
export async function importJDFile(base: string, file: File, title = ""): Promise<JD> {
  const query = new URLSearchParams({ filename: file.name, title });
  const res = await fetch(`${base}/api/jd/upload?${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!res.ok) return fail(res, `could not import ${file.name}`);
  return (await res.json()) as JD;
}

/** One line for the list: what it was, and how much of it there is. */
export function jdSummary(doc: JDSummary): string {
  const from = doc.filename || "pasted text";
  return `${doc.words} words · ${from}`;
}
