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
  },
});
