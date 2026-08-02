/**
 * Where this app is keeping the user's work, as `/api/storage` reports it.
 *
 * Mirrors `praxis.storage.describe()` — the shell displays what the launcher says rather
 * than deriving a path of its own, because only the Python side knows which backend is
 * active. Credentials are stripped server-side (`Backend.public_options`), so nothing
 * here has to be careful with `options`.
 */

export type StorageInfo = {
  /** `app` · `drive` · `cloud` — every kind the backend has registered is in `kinds`. */
  kind: string;
  label: string;
  /** The root everything below is written under. */
  root: string;
  subjects: string;
  progress: string;
  /** False when the backend is unreachable right now — `detail` says why. */
  available: boolean;
  detail: string;
  options: Record<string, unknown>;
  /** Where `storage.json` (the selection itself) lives — never inside `root`. */
  appDir: string;
  config: string;
  kinds: string[];
};

export async function fetchStorage(base: string): Promise<StorageInfo> {
  const res = await fetch(`${base}/api/storage`);
  if (!res.ok) {
    throw new Error(`GET ${base}/api/storage -> ${res.status}`);
  }
  return (await res.json()) as StorageInfo;
}

/** One line for the footer: what is holding the user's work, and where. */
export function storageSummary(info: StorageInfo): string {
  return `${info.available ? "" : "⚠️ "}${info.label} · ${info.root}`;
}
