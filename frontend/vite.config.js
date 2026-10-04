import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,

    allowedHosts: [
      "aqua-ai.us",
      "www.aqua-ai.us"
    ],

    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        timeout: 240000,
        proxyTimeout: 240000
      }
    }
  }
});
