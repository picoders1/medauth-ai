import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3100,
    strictPort: true,
    proxy: {
      // The API listens on 8015 (host) -> 8010 (container). The SPA talks to
      // /api and /ui as if same-origin; Vite forwards to the running stack.
      '/api': { target: 'http://localhost:8015', changeOrigin: true },
      '/ui': { target: 'http://localhost:8015', changeOrigin: true },
    },
  },
})