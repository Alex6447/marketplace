import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-сервер фронтенда. Запросы к API проксируются на тонкий FastAPI,
// поэтому фронт обращается к относительным путям (/api, /healthz) без CORS-проблем.
// Target — 127.0.0.1 (IPv4): на Windows `localhost` может резолвиться в IPv6 ::1,
// куда uvicorn по умолчанию не слушает.
// Адрес API настраивается через VITE_API_TARGET (дефолт — порт 8000). На некоторых
// Windows-машинах порт 8000 перехватывается security-софтом так, что Node-клиент
// (а значит и этот прокси) получает ECONNRESET, хотя curl работает; в таком случае
// поднимайте uvicorn на другом порту и задавайте VITE_API_TARGET=http://127.0.0.1:<порт>.
const apiTarget = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

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
      "/api": apiTarget,
      "/healthz": apiTarget,
    },
  },
});
