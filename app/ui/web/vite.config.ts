import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite serves the SPA on :5173 in dev; FastAPI proxies API calls.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
