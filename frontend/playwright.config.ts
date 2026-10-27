import { defineConfig, devices } from '@playwright/test'
import { API_PORT, API_URL, APP_PORT, APP_URL, SITE_PORT, SITE_URL } from './tests/e2e/ports.ts'

/**
 * End-to-end suite (`make e2e`). Fully offline: the backend runs on MOCK providers with its own data
 * directory (data/e2e, wiped and re-seeded from the committed fixture corpus on every run), whatever
 * the developer's .env says. Ports differ from `make dev` (8000/5173) so both can run side by side.
 */
const mockBackendEnv: Record<string, string> = {
  REASONING_PROVIDER: 'mock',
  SEGMENTATION_PROVIDER: 'mock',
  EMBEDDER: 'mock',
  // explicit blanks override whatever the repo-root .env holds: no key is ever loaded
  MODEL_API_KEY: '',
  BASETEN_API_KEY: '',
  PEXELS_ENABLED: '0',
  LIVE_SEARCH: '0', // the offline suite never calls a licensed source
  JOBS_SYNC: '0',
  DATA_DIR: './data/e2e',
  DATABASE_URL: 'sqlite:///./data/e2e/dle.sqlite',
  // the link fixture page is served from loopback, which the SSRF guard blocks by default
  LINK_ALLOW_PRIVATE_HOSTS: '127.0.0.1',
  PUBLIC_APP_URL: APP_URL,
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  use: {
    baseURL: APP_URL,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      // prepare (wipe + seed, jobs inline) then serve with background jobs
      command:
        'JOBS_SYNC=1 uv run python scripts/e2e_prepare.py && ' +
        `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../backend',
      url: `${API_URL}/api/health`,
      env: mockBackendEnv,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      // static fixtures written by e2e_prepare.py: link page with og:image, image page, MP4, uploads
      command: `python3 -m http.server ${SITE_PORT} --bind 127.0.0.1 --directory ../data/e2e/site`,
      url: `${SITE_URL}/article.html`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${APP_PORT} --strictPort`,
      url: APP_URL,
      env: { DLE_API_PROXY: API_URL },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
