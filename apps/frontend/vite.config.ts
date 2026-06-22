import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-сервер фронтенда. Запросы к API проксируются на тонкий FastAPI (порт 8000),
// поэтому фронт обращается к относительным путям (/api, /healthz) без CORS-проблем.
// Target — 127.0.0.1 (IPv4): на Windows `localhost` может резолвиться в IPv6 ::1,
// куда uvicorn по умолчанию не слушает.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
    },
  },
});
