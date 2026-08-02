import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri drives the dev server on a fixed port (see src-tauri/tauri.conf.json
// `build.devUrl`), so the port must not drift.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  build: {
    // src-tauri embeds this directory at compile time (`frontendDist`).
    outDir: "dist",
    emptyOutDir: true,
    target: "es2021",
  },
});
