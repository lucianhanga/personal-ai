/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Tauri serves the built assets; relative base keeps file:// loading working.
  base: "./",
  // Target modern Chromium (Tauri webview; tsconfig already targets ES2022). Also avoids esbuild
  // 0.28's refusal to down-transform modern syntax to vite's old es2020 default (#275 override).
  build: { target: "es2022" },
  server: { port: 5173, strictPort: true },
  preview: { port: 4173, strictPort: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Playwright specs live in e2e/ and are run by Playwright, not Vitest.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
