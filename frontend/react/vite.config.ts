import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into frontend/app, which FastAPI serves under /static/app (assets) and /app (the page): see backend/app/stack.py.
// `npm run dev` proxies the API to a local AXoR on :8000.
export default defineConfig({
  plugins: [react()],
  base: "/static/app/",
  build: { outDir: "../app", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
