import { invoke } from "@tauri-apps/api/core";

export type AppInfo = {
  name: string;
  version: string;
  tauri: boolean;
};

/** True when the frontend is served inside the Tauri webview rather than a browser. */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Ask the Rust backend who it is. The same bundle is served by `vite dev` in a plain
 * browser (where there is no backend to ask), so fall back rather than throw.
 */
export async function appInfo(): Promise<AppInfo> {
  if (!isTauri()) {
    return { name: "Praxis", version: "0.1.0", tauri: false };
  }
  return invoke<AppInfo>("app_info");
}

export type LauncherStatus = {
  state: "starting" | "ready" | "failed";
  url: string | null;
  detail: string;
};

/** Where a browser-hosted preview expects a hand-started `praxis-launch` to be. */
const WEB_LAUNCHER =
  (import.meta.env.VITE_PRAXIS_LAUNCHER as string | undefined) ?? "http://127.0.0.1:8000";

/**
 * Where the notebook library is being served from.
 *
 * In the desktop shell Rust owns the launcher process and reports its port. In a plain
 * browser nothing owns it, so probe the conventional port and say so if it is not there.
 */
export async function launcherStatus(): Promise<LauncherStatus> {
  if (isTauri()) {
    return invoke<LauncherStatus>("launcher_status");
  }
  try {
    const res = await fetch(`${WEB_LAUNCHER}/healthz`);
    if (res.ok) {
      return { state: "ready", url: WEB_LAUNCHER, detail: WEB_LAUNCHER };
    }
  } catch {
    /* not running — fall through */
  }
  return {
    state: "failed",
    url: null,
    detail: `no launcher at ${WEB_LAUNCHER} — start one with \`praxis-launch\`, or open the desktop shell`,
  };
}
