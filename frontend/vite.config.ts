import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // SSE streams through this proxy unbuffered; the backend runs on :8000 (make dev).
      // DLE_API_PROXY points it elsewhere (the e2e suite runs its own backend on :8765).
      '/api': { target: process.env.DLE_API_PROXY ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
})
