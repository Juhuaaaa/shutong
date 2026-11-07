/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import vuetify from "vite-plugin-vuetify";

const backend = process.env.SHUTONG_DEV_BACKEND ?? "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { proxy: { "/api": { target: backend, ws: true, changeOrigin: true } } },
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.ts"],
    setupFiles: ["src/test-setup.ts"],
    server: { deps: { inline: ["vuetify"] } },
  },
});
