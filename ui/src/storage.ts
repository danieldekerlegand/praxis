/**
 * Where this app is keeping the user's work, as `/api/storage` reports it.
 *
 * Mirrors `praxis.storage.describe()` — the shell displays what the launcher says rather
 * than deriving a path of its own, because only the Python side knows which backend is
 * active. Credentials are stripped server-side (`Backend.public_options`), so nothing
 * here has to be careful with `options`.
 */

/** One field of one backend's settings form, as `storage.FIELDS` defines it. */
export type StorageField = {
  key: string;
  label: string;
  required: boolean;
  /** A credential. Never sent back to us, so a blank one means "keep the stored value". */
  secret: boolean;
  value: string;
  /** True when a value is stored for it — how a secret is shown without being shown. */
  set: boolean;
};

/** One offer in the settings view: a backend, what it is for, and what it needs. */
export type StorageKind = {
  kind: string;
  label: string;
  blurb: string;
  fields: StorageField[];
};

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
  /** The whole settings form, from Python — the UI keeps no second copy of it. */
  backends: StorageKind[];
  /** True when the active backend has a copy somewhere else (today: cloud). */
  syncable: boolean;
};

/** What one sync moved. `synced: false` means this backend has nowhere to sync to. */
export type SyncReport = {
  kind: string;
  synced: boolean;
  detail?: string;
  pulled?: string[];
  pushed?: string[];
  moved?: number;
  remote?: number;
  local?: number;
};

/** The launcher's error bodies all carry `error`; fall back to the status line. */
async function fail(res: Response, what: string): Promise<never> {
  const body = await res.json().catch(() => null);
  throw new Error(body?.error || `${what} -> ${res.status}`);
}

export async function fetchStorage(base: string): Promise<StorageInfo> {
  const res = await fetch(`${base}/api/storage`);
  if (!res.ok) {
    throw new Error(`GET ${base}/api/storage -> ${res.status}`);
  }
  return (await res.json()) as StorageInfo;
}

/**
 * Move the user's work to another backend.
 *
 * The launcher verifies before it stores, so a rejected choice comes back as a thrown
 * `Error` carrying the reason — and the previous backend is still the active one. Nothing
 * is copied between roots: this changes where Praxis looks, and the old root keeps what
 * was in it.
 */
export async function selectStorage(
  base: string,
  kind: string,
  options: Record<string, string>,
): Promise<StorageInfo> {
  const res = await fetch(`${base}/api/storage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, options }),
  });
  if (!res.ok) return fail(res, `POST ${base}/api/storage`);
  return (await res.json()) as StorageInfo;
}

/** Reconcile the active backend with wherever its real copy lives (today: the bucket). */
export async function syncStorage(base: string): Promise<SyncReport> {
  const res = await fetch(`${base}/api/storage/sync`, { method: "POST" });
  if (!res.ok) return fail(res, `POST ${base}/api/storage/sync`);
  return (await res.json()) as SyncReport;
}

/** One line for the footer: what is holding the user's work, and where. */
export function storageSummary(info: StorageInfo): string {
  return `${info.available ? "" : "⚠️ "}${info.label} · ${info.root}`;
}

/** What a finished sync actually did, in one sentence. */
export function syncSummary(report: SyncReport): string {
  if (!report.synced) return report.detail || "nothing to sync";
  const { pulled = [], pushed = [] } = report;
  if (!pulled.length && !pushed.length) return "already up to date";
  const parts = [];
  if (pushed.length) parts.push(`${pushed.length} sent up`);
  if (pulled.length) parts.push(`${pulled.length} brought down`);
  return `synced — ${parts.join(", ")}`;
}
