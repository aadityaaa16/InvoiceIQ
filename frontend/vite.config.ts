import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Polling: file-change events don't cross the Windows -> Docker bind mount.
  server: { port: 5173, watch: { usePolling: true } },
});
