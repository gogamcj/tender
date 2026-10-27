/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버는 /api 요청을 백엔드(기본 8000번)로 넘긴다. 같은 출처로 보이므로 SameSite=Strict 쿠키가 동작한다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.BID_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { charts: ["recharts"], vendor: ["react", "react-dom", "react-router-dom"] } },
    },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: process.env.BID_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    css: false,
  },
});
