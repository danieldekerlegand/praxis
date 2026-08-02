import { useEffect, useState } from "react";
import { isTauri, pickFolder } from "./tauri";
import {
  selectStorage,
  syncStorage,
  syncSummary,
  type StorageInfo,
  type StorageKind,
} from "./storage";

/**
 * "Where should Praxis keep my work?" — the settings view for the storage backends.
 *
 * It holds no opinion about what a valid backend looks like. The kinds, their blurbs and
 * their fields all come from `/api/storage` (`praxis.storage.FIELDS`), and whether a
 * choice is usable is answered by `POST /api/storage`, which resolves, checks and creates
 * before it stores anything. So a rejected choice is shown here as the launcher's own
 * sentence, and the backend the user had is still the active one — this view cannot
 * strand them, because it never decides anything.
 *
 * The one thing the webview genuinely can't do is open a folder picker, which is the
 * `pick_folder` command in the shell. Outside the shell the text field is still there.
 */
export default function StorageSettings({
  base,
  info,
  onChanged,
}: {
  base: string;
  info: StorageInfo;
  /** Storage moved — the library is somewhere else now, so App refetches both. */
  onChanged: () => void;
}) {
  const [chosen, setChosen] = useState(info.kind);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // Seed each form from what is stored, and re-seed when the server's picture changes
  // (a switch, or a secret that has just been saved). Untouched fields therefore always
  // show the truth rather than whatever was typed into a form the user abandoned.
  useEffect(() => {
    const seeded: Record<string, Record<string, string>> = {};
    for (const backend of info.backends) {
      seeded[backend.kind] = Object.fromEntries(backend.fields.map((f) => [f.key, f.value]));
    }
    setValues(seeded);
    setChosen(info.kind);
  }, [info]);

  const set = (kind: string, key: string, value: string) =>
    setValues((all) => ({ ...all, [kind]: { ...all[kind], [key]: value } }));

  const missing = (backend: StorageKind) =>
    backend.fields.filter((f) => f.required && !(values[backend.kind]?.[f.key] || "").trim());

  const apply = async (backend: StorageKind) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const next = await selectStorage(base, backend.kind, values[backend.kind] || {});
      setNote(`Your work is now kept in ${next.label} — ${next.root}`);
      onChanged();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  const browse = async (kind: string, key: string) => {
    const picked = await pickFolder();
    if (picked) set(kind, key, picked);
  };

  const sync = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      setNote(syncSummary(await syncStorage(base)));
      onChanged();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="storage">
      <h1>Where your work is kept</h1>
      <p className="blurb">
        The subjects you define, the tutorials built into them and everything you have
        passed live under one folder. Point it wherever you like — switching only changes
        where Praxis looks, and never moves or deletes what is already somewhere else.
      </p>

      <p className={info.available ? "status" : "status error"}>
        <strong>{info.label}</strong> · <code>{info.root}</code>
        {info.detail && <span className="note">{info.detail}</span>}
      </p>

      {info.syncable && (
        <div className="buildrow">
          <button onClick={sync} disabled={busy}>
            Sync now
          </button>
          <span className="legend">
            Praxis keeps a working copy on this computer, so it runs with the network
            down. A sync sends up what you changed and brings down what changed elsewhere;
            it never deletes.
          </span>
        </div>
      )}

      {error && <p className="status error">{error}</p>}
      {note && !error && <p className="status">{note}</p>}

      <ul className="backends">
        {info.backends.map((backend) => {
          const active = backend.kind === info.kind;
          const open = backend.kind === chosen;
          const gaps = missing(backend);
          return (
            <li key={backend.kind} className={`backend${open ? " open" : ""}`}>
              <button className="pick" onClick={() => setChosen(backend.kind)}>
                <span className="radio">{open ? "◉" : "○"}</span>
                <span className="bname">
                  {backend.label}
                  {active && <span className="gate passed">in use</span>}
                </span>
                <span className="note">{backend.blurb}</span>
              </button>

              {open && (
                <div className="bform">
                  {backend.fields.map((field) => (
                    <label key={field.key}>
                      <span>{field.label}</span>
                      <span className="frow">
                        <input
                          type={field.secret ? "password" : "text"}
                          value={values[backend.kind]?.[field.key] ?? ""}
                          placeholder={
                            field.secret && field.set ? "•••••• (saved — leave blank to keep)" : ""
                          }
                          onChange={(e) => set(backend.kind, field.key, e.target.value)}
                        />
                        {/* No native dialog outside the shell, so don't offer one that
                            would do nothing — the field is typeable either way. */}
                        {field.key === "path" && isTauri() && (
                          <button className="ghost" onClick={() => browse(backend.kind, field.key)}>
                            Choose folder…
                          </button>
                        )}
                      </span>
                    </label>
                  ))}
                  <div className="buildrow">
                    <button onClick={() => apply(backend)} disabled={busy || gaps.length > 0}>
                      {active ? "Save" : `Keep my work in ${backend.label}`}
                    </button>
                    {gaps.length > 0 && (
                      <span className="legend">
                        needs {gaps.map((f) => f.label).join(", ")}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <p className="legend">
        The selection itself is kept in <code>{info.config}</code>, outside the folder it
        selects — so an unplugged drive still leaves Praxis able to tell you which drive it
        is looking for.
      </p>
    </main>
  );
}
