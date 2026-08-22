/**
 * The tutorial runtime: a JupyterLite site the shell serves over loopback.
 *
 * These types mirror `praxis-lite.json` as `praxis/lite.py` writes it, and the status
 * mirrors `src-tauri/src/lite.rs`. The site is static and its kernel is the browser's, so
 * everything here works in a bundle whose Python core is missing — which is exactly why
 * it is a second, independent status rather than a field on the launcher's.
 *
 * What it is NOT is the gate. The notebooks the site serves have had every graded region
 * stripped before staging and no answer key travels with them; questions, grading and
 * unlocks stay behind `launcher/app.py` (docs/reference/jupyterlite.md).
 */

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./tauri";

export const AVAILABLE = "available";
export const UNAVAILABLE = "unavailable-in-browser";

export type LiteTutorial = {
  /** The same `rel` `/api/library` and `/render/<rel>` use. */
  rel: string;
  /** The domain directory it belongs to — the manifest's own grouping key. */
  domain: string;
  title: string;
  status: typeof AVAILABLE | typeof UNAVAILABLE;
  /** Pyodide packages that cover its imports. */
  packages: string[];
  /** The modules Pyodide cannot provide — why it is not served. */
  missing: string[];
};

export type LiteDomain = { dir: string; name: string; title: string; blurb: string };

export type LiteManifest = {
  jupyterlite: string;
  pyodideKernel: string;
  pyodide: string;
  counts: { total: number; available: number; "unavailable-in-browser": number };
  domains: LiteDomain[];
  tutorials: LiteTutorial[];
};

export type LiteStatus = {
  state: "ready" | "missing";
  url: string | null;
  detail: string;
  manifest: LiteManifest | null;
};

/** Where a browser-hosted preview expects a statically served site, if it has one. */
const WEB_LITE = import.meta.env.VITE_PRAXIS_LITE as string | undefined;

/**
 * Where the in-browser runtime is being served from.
 *
 * In the desktop shell Rust serves the site it shipped and reports its port. In a plain
 * browser nothing serves it, unless `VITE_PRAXIS_LITE` names a site put on a static
 * server by hand — the same shape as `VITE_PRAXIS_LAUNCHER` in `tauri.ts`.
 */
export async function liteStatus(): Promise<LiteStatus> {
  if (isTauri()) {
    return invoke<LiteStatus>("lite_status");
  }
  if (WEB_LITE) {
    try {
      const res = await fetch(`${WEB_LITE}/praxis-lite.json`);
      if (res.ok) {
        return {
          state: "ready",
          url: WEB_LITE,
          detail: WEB_LITE,
          manifest: (await res.json()) as LiteManifest,
        };
      }
    } catch {
      /* not served — fall through */
    }
  }
  return {
    state: "missing",
    url: null,
    detail:
      "the in-browser tutorial runtime is served by the desktop shell (or by a static " +
      "server named in VITE_PRAXIS_LITE)",
    manifest: null,
  };
}

/** JupyterLab, opened on one tutorial. `path` is relative to the site's contents root. */
export function liteNotebookUrl(base: string, rel: string): string {
  const path = rel.split("/").map(encodeURIComponent).join("/");
  return `${base}/lab/index.html?path=${path}`;
}

/** The manifest's verdict for one topic, or `null` when the site knows nothing about it. */
export function tutorialFor(status: LiteStatus, rel: string): LiteTutorial | null {
  return status.manifest?.tutorials.find((t) => t.rel === rel) ?? null;
}

/** True when this topic can be opened and run in the window with no local Python. */
export function runsInBrowser(status: LiteStatus, rel: string): boolean {
  return status.state === "ready" && tutorialFor(status, rel)?.status === AVAILABLE;
}

/**
 * Why a topic cannot run in the browser, in the manifest's own terms — the
 * not-measured-rather-than-silently-zero half of the adoption, phrased for a reader.
 */
export function whyNotInBrowser(status: LiteStatus, rel: string): string {
  if (status.state !== "ready") return status.detail;
  const tutorial = tutorialFor(status, rel);
  if (!tutorial) {
    return "this tutorial is not in the site the bundle shipped — rebuild it with `make build-lite`";
  }
  if (tutorial.status === AVAILABLE) return "";
  return `Pyodide cannot provide ${tutorial.missing.join(", ")}, so this one cannot run in the browser`;
}

/** The site's tutorials grouped by domain, in the manifest's order. */
export function byDomain(manifest: LiteManifest): { domain: LiteDomain; tutorials: LiteTutorial[] }[] {
  return manifest.domains.map((domain) => ({
    domain,
    tutorials: manifest.tutorials.filter((t) => t.domain === domain.dir),
  }));
}
