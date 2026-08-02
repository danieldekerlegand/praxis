import { useEffect, useState } from "react";
import DefineSubject from "./DefineSubject";
import KnowledgeChecks from "./KnowledgeChecks";
import StorageSettings from "./StorageSettings";
import { itemFor, jobSummary, phaseBadge, useConstruction } from "./construct";
import { appInfo, isTauri, launcherStatus, type AppInfo, type LauncherStatus } from "./tauri";
import { fetchLibrary, labUrl, renderUrl, type Domain, type Library, type Topic } from "./library";
import { fetchStorage, storageSummary, type StorageInfo } from "./storage";

/** The core this shell is built on — mirrors the map in README.md. */
const CORE = [
  ["docs/notebook-rubric.md", "the definition of a complete tutorial"],
  ["scaffold_notebooks.py + curriculum.py", "the scaffolder"],
  ["nbstatus.py + tests/", "the completion gate (🔴 · 🟡 · ✅)"],
  ["launcher/", "browse · launch · render"],
  ["notebooks/", "221 seed tutorials across 10 domains"],
];

/** Read it, run it, or answer for it — the third is where progression is earned. */
const MODES = {
  render: "rendered",
  checks: "knowledge checks",
  lab: "live in Lab",
} as const;

type Mode = keyof typeof MODES;
type Reading = { topic: Topic; mode: Mode };

/** Browse what exists, define something new, or say where all of it is kept. */
const VIEWS = {
  library: "library",
  subjects: "define a subject",
  storage: "storage",
} as const;

type View = keyof typeof VIEWS;

export default function App() {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [view, setView] = useState<View>("library");
  const [status, setStatus] = useState<LauncherStatus>({
    state: "starting",
    url: null,
    detail: "starting the launcher…",
  });
  const [library, setLibrary] = useState<Library | null>(null);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeDir, setActiveDir] = useState<string | null>(null);
  const [reading, setReading] = useState<Reading | null>(null);

  useEffect(() => {
    appInfo().then(setInfo).catch(() => setInfo(null));
  }, []);

  // Poll until the launcher is up (Rust starts it in the background at boot), then load
  // the library once.
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const tick = async () => {
      const next = await launcherStatus().catch(
        (err): LauncherStatus => ({ state: "failed", url: null, detail: String(err) }),
      );
      if (!live) return;
      setStatus(next);
      if (next.state === "starting") {
        timer = window.setTimeout(tick, 600);
      }
    };
    void tick();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, []);

  // Where the user's own work is being written. Read once the launcher is up, and
  // re-read after a construction run — that is when something was actually stored.
  useEffect(() => {
    if (status.state !== "ready" || !status.url) return;
    fetchStorage(status.url).then(setStorage).catch(() => setStorage(null));
  }, [status]);

  useEffect(() => {
    if (status.state !== "ready" || !status.url || library) return;
    fetchLibrary(status.url)
      .then((lib) => {
        setLibrary(lib);
        setActiveDir((dir) => dir ?? lib.domains[0]?.dir ?? null);
      })
      .catch((err) => setError(String(err)));
  }, [status, library]);

  const active: Domain | null =
    library?.domains.find((d) => d.dir === activeDir) ?? library?.domains[0] ?? null;

  // Construction writes notebooks, so once a run settles drop the library and let the
  // effect above refetch it — the job's badges are replaced by nbstatus's own.
  const construction = useConstruction(status.url ?? "", () => {
    if (!status.url) return;
    fetchLibrary(status.url).then(setLibrary).catch(() => undefined);
    fetchStorage(status.url).then(setStorage).catch(() => undefined);
  });
  const { job } = construction;
  const unbuilt = active ? active.n - active.done : 0;

  // The open topic, re-read from the library rather than kept in `reading`: answering a
  // check refetches the library, and this is what makes the counts and the locks in the
  // reader move with it instead of showing the state the topic was opened in.
  const open: Topic | null = reading
    ? active?.topics.find((t) => t.rel === reading.topic.rel) ?? reading.topic
    : null;

  return (
    <div className="shell">
      <header>
        <div className="brand">📚 Praxis</div>
        {status.state === "ready" && (
          <nav className="views">
            {(Object.keys(VIEWS) as View[]).map((v) => (
              <button
                key={v}
                className={view === v ? "tab active" : "tab"}
                onClick={() => setView(v)}
              >
                {VIEWS[v]}
              </button>
            ))}
          </nav>
        )}
        {library ? (
          <div className="progress">
            <div className="bar">
              <span style={{ width: `${library.pct}%` }} />
            </div>
            <div className="legend">
              {library.pct}% complete · {library.badge.complete} {library.counts.complete} ·{" "}
              {library.badge.partial} {library.counts.partial} · {library.badge.scaffold}{" "}
              {library.counts.scaffold} &nbsp;/&nbsp; {library.total} notebooks
            </div>
          </div>
        ) : (
          <div className="progress legend">the seed library</div>
        )}
        <div className="host">{isTauri() ? "desktop shell" : "web preview"}</div>
      </header>

      {view === "storage" && status.url && storage ? (
        // A different backend is a different set of subjects, so drop the library and
        // let the effect above refetch it — otherwise the sidebar would still be showing
        // the modules of the drive we just switched away from.
        <StorageSettings
          base={status.url}
          info={storage}
          onChanged={() => {
            fetchStorage(status.url!).then(setStorage).catch(() => undefined);
            setLibrary(null);
            setReading(null);
            setActiveDir(null);
          }}
        />
      ) : view === "subjects" && status.url ? (
        // Scaffolding a subject writes notebooks; drop the library so the effect above
        // refetches it and the new module shows up in the sidebar with live badges.
        <DefineSubject
          base={status.url}
          construction={construction}
          onScaffolded={() => setLibrary(null)}
        />
      ) : library && active ? (
        <div className="layout">
          <nav className="sidebar">
            {library.domains.map((d) => (
              <button
                key={d.dir}
                className={`domain ${d.dir === active.dir ? "active" : ""}`}
                onClick={() => {
                  setActiveDir(d.dir);
                  setReading(null);
                }}
              >
                <span className="dname">{d.name}</span>
                <span className="dcount">
                  {d.done}/{d.n}
                </span>
              </button>
            ))}
          </nav>

          {reading ? (
            <main className="reader">
              <div className="readerbar">
                <button className="back" onClick={() => setReading(null)}>
                  ← {active.name}
                </button>
                <span className="rtitle">
                  {library.badge[open!.status]} {open!.title}
                  {open!.locked && (
                    <span className="lock" title={`finish ${open!.blockedBy} first`}>
                      🔒
                    </span>
                  )}
                </span>
                <span className="tabs">
                  {(Object.keys(MODES) as Mode[]).map((mode) => (
                    <button
                      key={mode}
                      className={reading.mode === mode ? "tab active" : "tab"}
                      onClick={() => setReading({ ...reading, mode })}
                    >
                      {MODES[mode]}
                      {mode === "checks" && open!.gated && (
                        <span className="count">
                          {open!.passed}/{open!.checks}
                        </span>
                      )}
                    </button>
                  ))}
                </span>
              </div>
              {reading.mode === "checks" ? (
                // Answering is what moves the gate, and the launcher records it, so
                // reload the library afterwards: a finished topic unlocks the next one.
                <div className="readerpane">
                  <KnowledgeChecks
                    base={status.url!}
                    rel={open!.rel}
                    onGraded={() => {
                      if (status.url) {
                        fetchLibrary(status.url).then(setLibrary).catch(() => undefined);
                      }
                    }}
                  />
                </div>
              ) : (
                <iframe
                  title={open!.title}
                  src={
                    reading.mode === "render"
                      ? renderUrl(status.url!, open!.rel)
                      : labUrl(library, open!.rel)
                  }
                />
              )}
              {reading.mode === "lab" && (
                <p className="hint">
                  Live notebooks need JupyterLab running: <code>praxis-lab</code>
                </p>
              )}
            </main>
          ) : (
            <main>
              <h1>{active.title}</h1>
              <p className="blurb">{active.blurb}</p>
              {active.gated > 0 && (
                <p className="legend">
                  🔒 Gated: {active.passed}/{active.gated} tutorials passed. Each one opens
                  when you pass the knowledge checks in the one before it.
                </p>
              )}

              <div className="buildrow">
                <button
                  onClick={() => construction.start({ domain: active.dir })}
                  disabled={construction.running || unbuilt === 0}
                >
                  {unbuilt === 0
                    ? "every notebook here is built"
                    : `Build ${unbuilt} notebook${unbuilt === 1 ? "" : "s"} with AI`}
                </button>
                <span className="legend">
                  Each one is written to <code>docs/notebook-rubric.md</code> and only
                  saved once it passes the completion gate. Already ✅ notebooks are left
                  alone, so this can be re-run.
                </span>
              </div>
              {job && (
                <p className={`status${job.error ? " error" : ""}`}>
                  {job.error || jobSummary(job)}
                </p>
              )}
              {construction.error && <p className="status error">{construction.error}</p>}

              <ul className="topics">
                {active.topics.map((t) => {
                  const item = itemFor(job, t.rel);
                  return (
                    <li
                      key={t.rel}
                      className={`topic status-${item?.badge || t.status}${
                        t.locked ? " locked" : ""
                      }`}
                    >
                      <span className="badge" title={item?.detail || undefined}>
                        {phaseBadge(item, library.badge, t.status)}
                      </span>
                      <span className="ttitle">
                        {t.title}
                        {t.recommended && (
                          <span className="rec" title="recommended addition">
                            ⭐
                          </span>
                        )}
                        {t.locked ? (
                          <span className="lock" title={`finish ${t.blockedBy} first`}>
                            🔒
                          </span>
                        ) : (
                          t.gated && (
                            <span
                              className={t.complete ? "gate passed" : "gate"}
                              title="knowledge checks passed"
                            >
                              {t.passed}/{t.checks}
                            </span>
                          )
                        )}
                        {item?.failures.length ? (
                          <span className="note">{item.failures[0]}</span>
                        ) : t.locked ? (
                          <span className="note">locked until you finish {t.blockedBy}</span>
                        ) : (
                          t.note && <span className="note">{t.note}</span>
                        )}
                      </span>
                      <span className="actions">
                        <button
                          className="ghost"
                          title={
                            t.status === "complete"
                              ? "rewrite this notebook from scratch"
                              : "fill this notebook to the rubric"
                          }
                          disabled={construction.running}
                          onClick={() =>
                            construction.start({ rel: t.rel }, t.status === "complete")
                          }
                        >
                          {t.status === "complete" ? "rebuild" : "build"}
                        </button>
                        <button
                          title={
                            t.locked
                              ? `pass ${t.blockedBy} to unlock this`
                              : t.gated
                                ? "answer the checks that unlock this tutorial"
                                : "no knowledge checks yet — build this topic to gate it"
                          }
                          disabled={t.locked || !t.gated}
                          onClick={() => setReading({ topic: t, mode: "checks" })}
                        >
                          {t.locked ? "🔒 locked" : "checks"}
                        </button>
                        <button
                          disabled={t.locked}
                          onClick={() => setReading({ topic: t, mode: "render" })}
                        >
                          open
                        </button>
                        <button
                          className="ghost"
                          disabled={t.locked}
                          onClick={() => setReading({ topic: t, mode: "lab" })}
                        >
                          in Lab
                        </button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </main>
          )}
        </div>
      ) : (
        <main>
          <h1>Praxis constructs interactive, gated notebook tutorials.</h1>
          <p className="blurb">
            You define a subject. AI agents build the tutorials to a rubric. The tutorials gate
            progression behind knowledge checks, so a learner advances by demonstrating
            understanding rather than by scrolling.
          </p>

          <section className="core">
            <h2>Built on</h2>
            <ul>
              {CORE.map(([piece, role]) => (
                <li key={piece}>
                  <code>{piece}</code>
                  <span>{role}</span>
                </li>
              ))}
            </ul>
          </section>

          <p className="status">
            {error
              ? `Library unavailable: ${error}`
              : status.state === "failed"
                ? `Library unavailable — ${status.detail}`
                : "Loading the seed library…"}
          </p>
        </main>
      )}

      <footer>
        {info
          ? `${info.name} v${info.version} · ${info.tauri ? "Tauri" : "browser"}`
          : "Praxis · running outside the desktop shell"}
        {status.state === "ready" && ` · library via ${status.url}`}
        {storage && (
          <>
            {" · "}
            <button
              className={storage.available ? "store" : "store error"}
              onClick={() => setView("storage")}
              title={
                storage.detail
                  ? `${storage.detail}\nsubjects: ${storage.subjects}\nprogress: ${storage.progress}`
                  : `subjects: ${storage.subjects}\nprogress: ${storage.progress}`
              }
            >
              {storageSummary(storage)}
            </button>
          </>
        )}
      </footer>
    </div>
  );
}
