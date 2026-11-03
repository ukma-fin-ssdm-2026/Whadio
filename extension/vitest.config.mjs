// Vitest comes from frontend/node_modules, which modules here cannot import, so tests use its globals.
// Its caches go there too: every file in extension/ is packaged into the extension.
export default {
  cacheDir: "../frontend/node_modules/.vite-extension",
  test: {
    environment: "node",
    globals: true,
    include: ["*.test.js"],
    fsModuleCachePath: "../frontend/node_modules/.vitest-cache-extension",
  },
};
