import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    lib: { entry: 'src/content.ts', formats: ['iife'], name: 'dleContent', fileName: () => 'content.js' },
  },
})
