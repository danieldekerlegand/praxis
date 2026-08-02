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
