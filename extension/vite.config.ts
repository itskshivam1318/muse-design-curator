import { copyFileSync, mkdirSync } from 'node:fs'
import { defineConfig } from 'vite'

// Background worker (ES module) + popup page. The content script is built separately
// (vite.content.config.ts) as a self-contained classic script for executeScript.
export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: { background: 'src/background.ts', popup: 'popup.html' },
      output: { entryFileNames: '[name].js' },
    },
  },
  plugins: [
    {
      name: 'copy-manifest',
      closeBundle() {
        mkdirSync('dist', { recursive: true })
        copyFileSync('manifest.json', 'dist/manifest.json')
      },
    },
  ],
})
