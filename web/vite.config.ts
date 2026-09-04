/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build into ../api/static so the FastAPI `api` component serves the bundle
// directly. In dev, proxy /api to the backend so the wizard talks to real routes.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../api/static",
    emptyOutDir: true,
    // @novnc/novnc's RFB (web/src/browser/BrowserSessionPage.tsx) uses
    // top-level await, which Vite's default baseline (chrome87/es2020/…)
    // rejects at transpile time — `npm run build` fails outright, though
    // `test` and `typecheck` pass because neither applies this target.
    // Do not lower this below a level that supports top-level await.
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // AgentsPage.*.test.tsx mount the whole page (MUI + router + every
    // section) in jsdom — ~2s per test when idle. With the default one worker
    // per core (16 on the dev box) and ~30 test files in flight at once they
    // starve each other and cross vitest's 5s default, so the pre-PR gate
    // sees timeouts that never reproduce in isolation. Bound the fan-out and
    // give those renders real headroom; do not lower these back to defaults.
    testTimeout: 15000,
    minWorkers: 1,
    maxWorkers: 4,
  },
});
