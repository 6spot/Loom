import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// C1-T9: one build serves public Chronicle routes and /studio/* routes.
// Deterministic asset filenames (no content hash) so the Rust
// chronicle-server can embed the build output at compile time with
// include_bytes! (hashed names cannot be named statically).
// Output goes to ../web/dist and is committed so `cargo test` works
// without a Node toolchain.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/v0": "http://127.0.0.1:8080",
    },
  },
});
