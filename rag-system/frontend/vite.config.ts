import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    host: true,
    allowedHosts: [
      "www.srj666.com",
      "srj666.com",
      "test.srj666.com",
    ],
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  plugins: [react()],
});
