/**
 * The gated tutorial, as a learner meets it.
 *
 * One section at a time: the launcher says which are unlocked, and a locked one arrives
 * with no questions in it at all, so this renders what it was given rather than deciding
 * anything. Every answer goes back to `POST /api/study/<rel>`, which grades it, records
 * it, and returns the gate as it now stands — the state below is always the server's.
 */

import { useEffect, useState } from "react";
import {
  fetchStudy,
  sectionMark,
  studySummary,
  submitAnswer,
  type Check,
  type Section,
  type Study as StudyState,
} from "./study";

type Props = {
  base: string;
  rel: string;
  /** Told after every graded answer, so the library's locks can catch up. */
  onGraded?: (state: StudyState) => void;
};

export default function KnowledgeChecks({ base, rel, onGraded }: Props) {
  const [study, setStudy] = useState<StudyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [grading, setGrading] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setStudy(null);
    setError(null);
    fetchStudy(base, rel)
      .then((next) => live && setStudy(next))
      .catch((err) => live && setError(String(err)));
    return () => {
      live = false;
    };
  }, [base, rel]);

  async function check(item: Check) {
    setGrading(item.id);
    setError(null);
    try {
      const { state } = await submitAnswer(base, rel, item.id, draftFor(item));
      setStudy(state);
      onGraded?.(state);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGrading(null);
    }
  }

  function draftFor(item: Check): string {
    const draft = drafts[item.id];
    return draft === undefined ? (item.kind === "code" ? item.starter ?? "" : "") : draft;
  }

  const set = (id: string, value: string) => setDrafts((d) => ({ ...d, [id]: value }));

  if (error) return <p className="status error">{error}</p>;
  if (!study) return <p className="status">Opening the checks…</p>;

  return (
    <div className="study">
      <p className={`status${study.locked ? " locked" : ""}`}>{studySummary(study)}</p>

      {study.gated ? (
        study.sections.map((section) => (
          <SectionBlock
            key={section.section}
            section={section}
            grading={grading}
            draftFor={draftFor}
            set={set}
            onCheck={check}
          />
        ))
      ) : (
        <p className="legend">
          Knowledge checks are written alongside the notebook when it is built. Build this
          topic to gate it.
        </p>
      )}
    </div>
  );
}

function SectionBlock({
  section,
  grading,
  draftFor,
  set,
  onCheck,
}: {
  section: Section;
  grading: string | null;
  draftFor: (item: Check) => string;
  set: (id: string, value: string) => void;
  onCheck: (item: Check) => void;
}) {
  return (
    <section
      className={`checkgroup ${section.locked ? "locked" : section.complete ? "done" : ""}`}
    >
      <h3>
        <span className="mark">{sectionMark(section)}</span>
        {section.section}
        <span className="count">
          {section.passed}/{section.n}
        </span>
      </h3>

      {section.locked ? (
        <p className="legend">
          Locked — pass the {section.n === 1 ? "check" : `${section.n} checks`} in the
          sections above to unlock {section.section}.
        </p>
      ) : (
        section.checks.map((item) => (
          <article key={item.id} className={`check ${item.answered ? (item.passed ? "passed" : "failed") : ""}`}>
            <p className="prompt">{item.prompt}</p>

            {item.kind === "choice" && (
              <ul className="options">
                {(item.options ?? []).map((option, i) => (
                  <li key={i}>
                    <label>
                      <input
                        type="radio"
                        name={item.id}
                        checked={draftFor(item) === String(i)}
                        onChange={() => set(item.id, String(i))}
                      />
                      {option}
                    </label>
                  </li>
                ))}
              </ul>
            )}

            {item.kind !== "choice" && (
              <textarea
                className={item.kind === "code" ? "code" : ""}
                rows={item.kind === "code" ? 8 : 4}
                spellCheck={item.kind === "short"}
                placeholder={
                  item.kind === "code" ? "your code here" : "answer in your own words"
                }
                value={draftFor(item)}
                onChange={(e) => set(item.id, e.target.value)}
              />
            )}

            <div className="checkrow">
              <button disabled={grading !== null} onClick={() => onCheck(item)}>
                {grading === item.id
                  ? "grading…"
                  : item.answered
                    ? "try again"
                    : "check my answer"}
              </button>
              {item.answered && (
                <span className="verdict">
                  {item.passed ? "✅ passed" : "❌ not yet"}
                  {item.outcome?.graded_by && item.outcome.graded_by !== "auto" && (
                    <span className="legend"> · graded by {item.outcome.graded_by}</span>
                  )}
                </span>
              )}
            </div>

            {item.answered && (item.outcome?.detail || item.explanation) && (
              <pre className="feedback">{item.outcome?.detail || item.explanation}</pre>
            )}
            {item.answered && item.explanation && item.outcome?.detail !== item.explanation && (
              <p className="legend">{item.explanation}</p>
            )}
          </article>
        ))
      )}
    </section>
  );
}
