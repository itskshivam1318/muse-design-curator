import { copyFileSync, mkdirSync } from 'node:fs'
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: { background: 'src/background.ts' },
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
