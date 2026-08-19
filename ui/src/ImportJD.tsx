import { useEffect, useState } from "react";
import {
  fetchJD,
  fetchJDs,
  importJDFile,
  importJDText,
  jdSummary,
  type JD,
  type JDSummary,
} from "./jd";

/** What the file picker offers — exactly the suffixes `praxis.jd.KINDS` can read. */
const ACCEPT = ".txt,.md,.markdown,.pdf,.docx";

/** How a posting arrived, for the confirmation line. */
const KIND_LABEL: Record<string, string> = {
  text: "plain text",
  markdown: "Markdown",
  pdf: "PDF",
  docx: "Word document",
};

const NEW = ""; // the sidebar entry for "nothing selected" — show the import form

/**
 * Import a job description, by pasting it or by picking the file it arrived as.
 *
 * The front of a different funnel: everything else in Praxis starts from a subject the
 * user *types*, this starts from a posting they already have. The launcher parses
 * `.txt` / `.md` / `.pdf` / `.docx` down to **one canonical plain text** and persists it
 * under the active storage backend — no model is involved, so this works with no key
 * configured.
 *
 * What is shown back after an import is deliberately not the response body: the id comes
 * back, and the text below is then re-read with `GET /api/jd/<id>`. So the confirmation
 * is the document that actually landed on the backend, not an echo of what was sent.
 */
export default function ImportJD({ base }: { base: string }) {
  const [jds, setJds] = useState<JDSummary[] | null>(null);
  const [id, setId] = useState<string>(NEW);
  const [doc, setDoc] = useState<JD | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchJDs(base)
      .then(setJds)
      .catch((err) => {
        setJds([]);
        setError(String(err));
      });
  }, [base]);

  // Read the selected posting back off the backend — this is the round trip, and the
  // reason the text on screen can't be something that was never stored.
  useEffect(() => {
    if (!id) {
      setDoc(null);
      return;
    }
    let live = true;
    fetchJD(base, id)
      .then((next) => live && setDoc(next))
      .catch((err) => live && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      live = false;
    };
  }, [base, id]);

  async function imported(next: JD) {
    // Same id means the same posting — re-importing rewrites one document, so replace
    // rather than prepend, exactly as the launcher does on disk.
    setJds((prev) => [next, ...(prev ?? []).filter((s) => s.id !== next.id)]);
    setId(next.id);
    setText("");
    setTitle("");
    setFile(null);
  }

  async function importPaste(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await imported(await importJDText(base, text, title));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function importUpload(picked: File) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await imported(await importJDFile(base, picked, title));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="layout">
      <nav className="sidebar">
        <button
          className={`domain ${id === NEW ? "active" : ""}`}
          onClick={() => {
            setId(NEW);
            setError(null);
          }}
        >
          <span className="dname">＋ Import a JD</span>
        </button>
        {(jds ?? []).map((s) => (
          <button
            key={s.id}
            className={`domain ${s.id === id ? "active" : ""}`}
            title={jdSummary(s)}
            onClick={() => {
              setId(s.id);
              setError(null);
            }}
          >
            <span className="dname">{s.title}</span>
            <span className="dcount">{s.words}</span>
          </button>
        ))}
      </nav>

      <main>
        {id && doc ? (
          <>
            <h1>{doc.title}</h1>
            <p className="blurb">
              Imported as {KIND_LABEL[doc.kind] ?? doc.kind}
              {doc.filename ? ` from ${doc.filename}` : " you pasted"} — {doc.words} words,{" "}
              {doc.chars} characters of canonical plain text.
            </p>
            <p className="legend">
              <code>{doc.id}</code> · {doc.source} · {doc.created} · read back off the
              storage backend just now, so this is what was actually stored.
            </p>
            <pre className="jdtext">{doc.text}</pre>
            {error && <p className="status error">{error}</p>}
          </>
        ) : (
          <>
            <h1>Bring a job description</h1>
            <p className="blurb">
              Paste the posting, or pick the file it arrived as — <code>.txt</code>,{" "}
              <code>.md</code>, <code>.pdf</code> or <code>.docx</code>. Praxis normalizes
              it to one plain-text document and keeps it with the rest of your work. No
              model is called and no key is needed for this step.
            </p>
            <form className="define" onSubmit={importPaste}>
              <input
                className="jdtitle"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title (optional — otherwise taken from the posting)"
                disabled={busy}
              />
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={12}
                placeholder="Paste the whole posting here — responsibilities, requirements, the lot."
                disabled={busy}
              />
              <div className="defineopts">
                <button type="submit" disabled={busy || !text.trim()}>
                  {busy ? "importing…" : "Import pasted text"}
                </button>
                <label className="jdpick">
                  <span>or a file</span>
                  <input
                    type="file"
                    accept={ACCEPT}
                    disabled={busy}
                    onChange={(e) => {
                      const picked = e.target.files?.[0] ?? null;
                      setFile(picked);
                      e.target.value = ""; // let the same file be picked again after a fix
                      if (picked) void importUpload(picked);
                    }}
                  />
                </label>
              </div>
            </form>
            {busy && (
              <p className="status">
                Reading {file ? file.name : "the posting"} — parsing it down to plain text.
              </p>
            )}
            {error && <p className="status error">{error}</p>}
            {jds?.length === 0 && !busy && !error && (
              <p className="status">
                Nothing imported yet. A scanned or image-only PDF has no text to read —
                paste it instead, and Praxis will say so rather than store an empty
                document.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
