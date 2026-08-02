import { useEffect, useState } from "react";
import DefineSubject from "./DefineSubject";
import { appInfo, isTauri, launcherStatus, type AppInfo, type LauncherStatus } from "./tauri";
import { fetchLibrary, labUrl, renderUrl, type Domain, type Library, type Topic } from "./library";

/** The core this shell is built on — mirrors the map in README.md. */
const CORE = [
  ["docs/notebook-rubric.md", "the definition of a complete tutorial"],
  ["scaffold_notebooks.py + curriculum.py", "the scaffolder"],
  ["nbstatus.py + tests/", "the completion gate (🔴 · 🟡 · ✅)"],
  ["launcher/", "browse · launch · render"],
  ["notebooks/", "221 seed tutorials across 10 domains"],
];

type Reading = { topic: Topic; mode: "render" | "lab" };

/** Browse what exists, or define something new. */
type View = "library" | "subjects";

export default function App() {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [view, setView] = useState<View>("library");
  const [status, setStatus] = useState<LauncherStatus>({
    state: "starting",
    url: null,
    detail: "starting the launcher…",
  });
  const [library, setLibrary] = useState<Library | null>(null);
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

  return (
    <div className="shell">
      <header>
        <div className="brand">📚 Praxis</div>
        {status.state === "ready" && (
          <nav className="views">
            {(["library", "subjects"] as const).map((v) => (
              <button
                key={v}
                className={view === v ? "tab active" : "tab"}
                onClick={() => setView(v)}
              >
                {v === "library" ? "library" : "define a subject"}
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

      {view === "subjects" && status.url ? (
        <DefineSubject base={status.url} />
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
                  {library.badge[reading.topic.status]} {reading.topic.title}
                </span>
                <span className="tabs">
                  {(["render", "lab"] as const).map((mode) => (
                    <button
                      key={mode}
                      className={reading.mode === mode ? "tab active" : "tab"}
                      onClick={() => setReading({ ...reading, mode })}
                    >
                      {mode === "render" ? "rendered" : "live in Lab"}
                    </button>
                  ))}
                </span>
              </div>
              <iframe
                title={reading.topic.title}
                src={
                  reading.mode === "render"
                    ? renderUrl(status.url!, reading.topic.rel)
                    : labUrl(library, reading.topic.rel)
                }
              />
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
              <ul className="topics">
                {active.topics.map((t) => (
                  <li key={t.rel} className={`topic status-${t.status}`}>
                    <span className="badge">{library.badge[t.status]}</span>
                    <span className="ttitle">
                      {t.title}
                      {t.recommended && (
                        <span className="rec" title="recommended addition">
                          ⭐
                        </span>
                      )}
                      {t.note && <span className="note">{t.note}</span>}
                    </span>
                    <span className="actions">
                      <button onClick={() => setReading({ topic: t, mode: "render" })}>open</button>
                      <button
                        className="ghost"
                        onClick={() => setReading({ topic: t, mode: "lab" })}
                      >
                        in Lab
                      </button>
                    </span>
                  </li>
                ))}
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
      </footer>
    </div>
  );
}
