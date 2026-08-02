import { useEffect, useState } from "react";
import { appInfo, isTauri, type AppInfo } from "./tauri";

/** The core this shell is built on — mirrors the map in README.md. */
const CORE = [
  ["docs/notebook-rubric.md", "the definition of a complete tutorial"],
  ["scaffold_notebooks.py + curriculum.py", "the scaffolder"],
  ["nbstatus.py + tests/", "the completion gate (🔴 · 🟡 · ✅)"],
  ["launcher/", "browse · launch · render"],
  ["notebooks/", "221 seed tutorials across 10 domains"],
];

export default function App() {
  const [info, setInfo] = useState<AppInfo | null>(null);

  useEffect(() => {
    appInfo().then(setInfo).catch(() => setInfo(null));
  }, []);

  return (
    <div className="shell">
      <header>
        <div className="brand">📚 Praxis</div>
        <div className="host">{isTauri() ? "desktop shell" : "web preview"}</div>
      </header>

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
          Shell scaffolded — no features wired up yet. Browsing the seed library lands next.
        </p>
      </main>

      <footer>
        {info
          ? `${info.name} v${info.version} · ${info.tauri ? "Tauri" : "browser"}`
          : "Praxis · running outside the desktop shell"}
      </footer>
    </div>
  );
}
