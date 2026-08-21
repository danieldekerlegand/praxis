import { useEffect, useState } from "react";
import {
  acceptSuggestion,
  dropSuggestion,
  editSuggestion,
  fetchSuggestions,
  type Suggestion,
  type SuggestionReview as SuggestionReviewData,
} from "./suggestions";

/** A projection of the launcher's review state: no gap classification or unlock logic lives here. */
export default function SuggestionReview({
  base,
  jdId,
  onAccepted,
}: {
  base: string;
  jdId: string;
  onAccepted: (slug: string) => void;
}) {
  const [review, setReview] = useState<SuggestionReviewData | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setReview(null);
    setError(null);
    fetchSuggestions(base, jdId)
      .then((next) => live && setReview(next))
      .catch((err) => live && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      live = false;
    };
  }, [base, jdId]);

  function beginEdit(row: Suggestion) {
    setEditing(row.id);
    setGoal(row.goal);
    setError(null);
  }

  async function saveEdit(id: string) {
    if (!goal.trim() || busy) return;
    setBusy(id);
    setError(null);
    try {
      setReview(await editSuggestion(base, jdId, id, goal));
      setEditing(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function drop(id: string) {
    if (busy) return;
    setBusy(id);
    setError(null);
    try {
      setReview(await dropSuggestion(base, jdId, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function accept(row: Suggestion) {
    if (busy) return;
    setBusy(row.id);
    setError(null);
    try {
      const result = await acceptSuggestion(base, jdId, row.id);
      onAccepted(result.slug);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="suggestions">
      <h2>Suggested tutorials</h2>
      <p className="blurb">
        These are the gaps the launcher found in this posting. Review the goal, drop what
        you do not need, or accept one to continue in the subject builder.
      </p>
      {error && <p className="status error">{error}</p>}
      {!review && !error && <p className="status">Loading suggestions…</p>}
      {review && review.suggestions.length === 0 && (
        <p className="status">No unfilled suggestions remain for this posting.</p>
      )}
      <ul className="suggestionlist">
        {review?.suggestions.map((row) => (
          <li className="suggestion" key={row.id}>
            <div className="suggestionhead">
              <div>
                <h3>{row.title}</h3>
                <span className="suggestionmeta">
                  {row.requirement.kind} · {row.requirement.importance} · {row.coverage}
                </span>
              </div>
              <div className="actions">
                <button className="ghost" disabled={busy === row.id} onClick={() => beginEdit(row)}>
                  edit
                </button>
                <button className="ghost" disabled={busy === row.id} onClick={() => void drop(row.id)}>
                  drop
                </button>
                <button disabled={busy === row.id} onClick={() => void accept(row)}>
                  {busy === row.id ? "accepting…" : "accept"}
                </button>
              </div>
            </div>
            <p className="suggestionwhy">{row.rationale}</p>
            <p className="suggestionevidence">From the posting: “{row.requirement.evidence}”</p>
            {editing === row.id ? (
              <div className="suggestionedit">
                <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} />
                <div className="actions">
                  <button disabled={busy === row.id || !goal.trim()} onClick={() => void saveEdit(row.id)}>
                    save goal
                  </button>
                  <button className="ghost" disabled={busy === row.id} onClick={() => setEditing(null)}>
                    cancel
                  </button>
                </div>
              </div>
            ) : (
              <p className="goalquote">“{row.goal}”</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
