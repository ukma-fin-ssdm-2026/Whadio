import { fileURLToPath } from "node:url";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: "react",
      // A chunk's first import can outlast Testing Library's 1 s wait on a busy runner.
      autoCodeSplitting: !process.env.VITEST,
      routeFileIgnorePattern: "\\.test\\.",
      // The default header turns type checking off, a suppression the commit hook refuses.
      routeTreeFileHeader: [],
    }),
    react(),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    // Vitest blanks every CSS import not listed here, even a ?raw one, which would read as "".
    css: { include: [/\/styles\.css\?raw$/] },
    setupFiles: ["src/shared/testing/setup.ts"],
  },
});
