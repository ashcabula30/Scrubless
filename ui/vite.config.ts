import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by the Python app server (footage_finder/static).
// `npm run dev` proxies the API to a running `footage serve`.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../footage_finder/static", emptyOutDir: true },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:7792" } },
});
