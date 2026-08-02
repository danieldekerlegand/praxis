import { useEffect, useState } from "react";
import { defineSubject, fetchSubjects, type Subject } from "./subjects";

const SIZES = [3, 4, 5, 6, 7, 8];
const NEW = "";  // the sidebar entry for "no subject selected" — show the form

/**
 * Define a subject and review what the AI made of it.
 *
 * The user types a goal; the launcher asks the configured model for a curriculum,
 * persists it under notebooks/subjects/<slug>/, and hands it back. Nothing is written
 * into the library until the curriculum below is scaffolded into notebooks.
 */
export default function DefineSubject({ base }: { base: string }) {
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [slug, setSlug] = useState<string>(NEW);
  const [goal, setGoal] = useState("");
  const [modules, setModules] = useState(5);
  const [topics, setTopics] = useState(6);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSubjects(base)
      .then(setSubjects)
      .catch((err) => {
        setSubjects([]);
        setError(String(err));
      });
  }, [base]);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !goal.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const subject = await defineSubject(base, goal, {
        modules,
        topicsPerModule: topics,
      });
      setSubjects((prev) => [subject, ...(prev ?? []).filter((s) => s.slug !== subject.slug)]);
      setSlug(subject.slug);
      setGoal("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const active = subjects?.find((s) => s.slug === slug) ?? null;

  return (
    <div className="layout">
      <nav className="sidebar">
        <button
          className={`domain ${slug === NEW ? "active" : ""}`}
          onClick={() => setSlug(NEW)}
        >
          <span className="dname">＋ New subject</span>
        </button>
        {(subjects ?? []).map((s) => (
          <button
            key={s.slug}
            className={`domain ${s.slug === slug ? "active" : ""}`}
            onClick={() => setSlug(s.slug)}
          >
            <span className="dname">{s.title}</span>
            <span className="dcount">{s.n_topics}</span>
          </button>
        ))}
      </nav>

      <main>
        {active ? (
          <>
            <h1>{active.title}</h1>
            <p className="blurb">{active.blurb}</p>
            <p className="goalquote">“{active.goal}”</p>
            <p className="legend">
              {active.modules.length} modules · {active.n_topics} notebooks ·{" "}
              {active.model ? `written by ${active.model}` : "curriculum"} ·{" "}
              <code>notebooks/subjects/{active.slug}/curriculum.json</code>
            </p>

            {active.modules.map((m) => (
              <section className="module" key={m.dir}>
                <h2>{m.title}</h2>
                <p className="blurb">{m.blurb}</p>
                <ul className="topics">
                  {m.topics.map((t) => (
                    <li className="topic" key={t.slug}>
                      <span className="badge" title={t.runnable ? "runnable" : "conceptual"}>
                        {t.runnable ? "▶" : "◇"}
                      </span>
                      <span className="ttitle">
                        {t.title}
                        {t.note && <span className="note">{t.note}</span>}
                      </span>
                      <span className="actions">
                        <code>{t.slug}.ipynb</code>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            <p className="status">
              Review the curriculum above. Scaffolding it turns every topic into a
              rubric-shaped notebook in the library — one file per row.
            </p>
          </>
        ) : (
          <>
            <h1>What do you want to learn?</h1>
            <p className="blurb">
              Describe the subject or goal in your own words. Praxis asks your model for a
              curriculum — modules, then one notebook per topic — and saves it here for
              review before any notebook is written.
            </p>
            <form className="define" onSubmit={generate}>
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                rows={4}
                placeholder="e.g. I want to get good enough at embedded Rust to write firmware for an STM32 board"
                disabled={busy}
              />
              <div className="defineopts">
                <label>
                  modules
                  <select
                    value={modules}
                    onChange={(e) => setModules(Number(e.target.value))}
                    disabled={busy}
                  >
                    {SIZES.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  topics each
                  <select
                    value={topics}
                    onChange={(e) => setTopics(Number(e.target.value))}
                    disabled={busy}
                  >
                    {SIZES.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="submit" disabled={busy || !goal.trim()}>
                  {busy ? "generating…" : "Generate curriculum"}
                </button>
              </div>
            </form>
            {busy && (
              <p className="status">
                Asking your model for a curriculum — this takes a few seconds.
              </p>
            )}
            {error && <p className="status error">{error}</p>}
            {subjects?.length === 0 && !busy && !error && (
              <p className="status">
                No subjects defined yet. Your key stays yours — set{" "}
                <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or{" "}
                <code>PRAXIS_LLM_BASE_URL</code> before generating.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
