import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The dashboard only talks to the FastAPI backend. In development Vite proxies /api
// (including the WebSocket upgrade) to the backend, so the browser sees a single origin
// and the HttpOnly session cookie is sent on both REST and WebSocket requests. That keeps
// authentication and CSRF behaviour identical in development and avoids CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
