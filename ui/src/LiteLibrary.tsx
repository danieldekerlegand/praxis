import { useState } from "react";
import {
  AVAILABLE,
  byDomain,
  liteNotebookUrl,
  type LiteStatus,
  type LiteTutorial,
} from "./lite";

/**
 * The library as the bundled JupyterLite site alone can serve it — no launcher, no Python.
 *
 * This is what the window falls back to when the Python core is missing or failed to
 * start: the site is static and carries its own manifest, so the tutorials it shipped can
 * still be browsed and RUN. What it honestly cannot do is anything the launcher owns —
 * live ✅/🔴 badges, knowledge checks, progression, and construction — so it says so
 * rather than drawing an emptier version of the real library and letting the learner
 * wonder. `docs/reference/jupyterlite.md` is the split it renders.
 */
export default function LiteLibrary({ lite, why }: { lite: LiteStatus; why: string }) {
  const manifest = lite.manifest;
  const groups = manifest ? byDomain(manifest) : [];
  const [activeDir, setActiveDir] = useState<string | null>(null);
  const [open, setOpen] = useState<LiteTutorial | null>(null);

  if (!manifest || !lite.url) return null;
  const active = groups.find((g) => g.domain.dir === activeDir) ?? groups[0];
  if (!active) return null;
  const runnable = active.tutorials.filter((t) => t.status === AVAILABLE).length;

  return (
    <div className="layout">
      <nav className="sidebar">
        {groups.map(({ domain, tutorials }) => (
          <button
            key={domain.dir}
            className={`domain ${domain.dir === active.domain.dir ? "active" : ""}`}
            onClick={() => {
              setActiveDir(domain.dir);
              setOpen(null);
            }}
          >
            <span className="dname">{domain.name}</span>
            <span className="dcount">
              {tutorials.filter((t) => t.status === AVAILABLE).length}/{tutorials.length}
            </span>
          </button>
        ))}
      </nav>

      {open ? (
        <main className="reader">
          <div className="readerbar">
            <button className="back" onClick={() => setOpen(null)}>
              ← {active.domain.name}
            </button>
            <span className="rtitle">{open.title}</span>
          </div>
          <iframe title={open.title} src={liteNotebookUrl(lite.url, open.rel)} />
          <p className="hint">
            Running in the browser on a Pyodide kernel — no local Python. Knowledge checks
            and progression need the Python core (see above).
          </p>
        </main>
      ) : (
        <main>
          <h1>{active.domain.title}</h1>
          <p className="blurb">{active.domain.blurb}</p>
          <p className="status error">{why}</p>
          <p className="legend">
            You can still read and run the {manifest.counts.available} tutorials this build
            shipped: they run on a Pyodide kernel in this window (JupyterLite{" "}
            {manifest.jupyterlite}, Pyodide {manifest.pyodide}). Knowledge checks,
            progression and building new tutorials are the Python core's, so they are
            unavailable until it starts.
          </p>
          <p className="legend">
            🔒 {runnable}/{active.tutorials.length} of this module's tutorials can run in
            the browser. The rest need packages Pyodide does not provide and are listed
            here as unavailable rather than opened and left to fail at their first import.
          </p>

          <ul className="topics">
            {active.tutorials.map((t) => {
              const available = t.status === AVAILABLE;
              return (
                <li key={t.rel} className={`topic${available ? "" : " locked"}`}>
                  <span className="badge">{available ? "📓" : "🚫"}</span>
                  <span className="ttitle">
                    {t.title}
                    {!available && (
                      <span className="note">
                        needs {t.missing.join(", ")} — not available in the browser
                      </span>
                    )}
                  </span>
                  <span className="actions">
                    <button disabled={!available} onClick={() => setOpen(t)}>
                      open
                    </button>
                  </span>
                </li>
              );
            })}
          </ul>
        </main>
      )}
    </div>
  );
}
