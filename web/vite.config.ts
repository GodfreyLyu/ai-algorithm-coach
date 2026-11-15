/** File purpose: Build the local UI and proxy API calls during development. */
import { defineConfig } from "vite";

export default defineConfig({
  // Vite does not discover our explicit .jsonc type-check configuration.
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/v1": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
