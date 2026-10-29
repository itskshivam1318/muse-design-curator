import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { type BrowserContext, chromium, expect, test, type Worker } from '@playwright/test'
import { apiJson, boardItems, expectItemCount, itemButton, openLibrary } from './helpers.ts'
import { API_URL, APP_URL, SITE_URL } from './ports.ts'

// the extension APIs, as seen inside the service worker (types live in the extension package)
declare const chrome: any

const DIST = resolve(import.meta.dirname, '../../../extension/dist')

/**
 * The built extension (`make ext`) loaded into Chromium. The copy used here differs from extension/dist
 * in one line: its host permissions also cover 127.0.0.1 on any port, because the e2e backend and
 * fixture site run on 127.0.0.1:8765 / :8766 rather than the shipped localhost:8000.
 */
function extensionCopy(): string {
  const dir = mkdtempSync(join(tmpdir(), 'dle-ext-'))
  cpSync(DIST, dir, { recursive: true })
  const manifestPath = join(dir, 'manifest.json')
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  manifest.host_permissions = [...manifest.host_permissions, 'http://127.0.0.1/*']
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))
  return dir
}

let extDir = ''
let context: BrowserContext
let worker: Worker

test.beforeAll(async () => {
  extDir = extensionCopy()
  context = await chromium.launchPersistentContext('', {
    channel: 'chromium', // the full Chromium build: headless mode with extension support
    args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`],
    viewport: { width: 1280, height: 860 },
  })
  worker = context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'))
})

test.afterAll(async () => {
  await context?.close()
  if (extDir) rmSync(extDir, { recursive: true, force: true })
})

test('extension: pair, right-click "Add to board" on an image, the item appears on the board', async () => {
  const extensionId = new URL(worker.url()).host
  const board = await apiJson<{ id: string }>('/boards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'E2E extension captures' }),
  })

  await test.step('point the extension at the e2e servers', async () => {
    await worker.evaluate(
      ({ apiBase, appUrl }) => chrome.storage.local.set({ apiBase, appUrl }),
      { apiBase: API_URL, appUrl: APP_URL },
    )
  })

  const app = await context.newPage()
  let code = ''
  await test.step('the app shows a pairing code', async () => {
    await app.goto(`${APP_URL}/boards/${board.id}`)
    await openLibrary(app)
    await app.getByRole('button', { name: /Get the Chrome extension/ }).click()
    const shown = app.locator('.pair-code')
    await expect(shown).toHaveText(/^\d{3} \d{3}$/)
    code = (await shown.textContent())!.replace(/\D/g, '')
  })

  await test.step('pair in the popup and choose the board', async () => {
    const popup = await context.newPage()
    await popup.goto(`chrome-extension://${extensionId}/popup.html`)
    await popup.locator('#code').fill(code)
    await popup.getByRole('button', { name: 'Pair' }).click()
    const select = popup.locator('select#board')
    await expect(select).toBeVisible()
    await select.selectOption(board.id)
    await expect
      .poll(() => worker.evaluate(() => chrome.storage.local.get('lastBoardId').then((s: { lastBoardId?: string }) => s.lastBoardId)))
      .toBe(board.id)
    await popup.close()
  })

  await test.step('right-click the fixture image: "Add to board"', async () => {
    const gallery = await context.newPage()
    await gallery.goto(`${SITE_URL}/gallery.html`)
    const img = gallery.locator('img#watch')
    await expect(img).toBeVisible()
    await img.click({ button: 'right' })
    // Playwright cannot click items in Chromium's native context menu, so deliver the same
    // contextMenus.onClicked event the menu click produces to the extension's own handler.
    const srcUrl = await img.evaluate((el) => (el as HTMLImageElement).currentSrc)
    const dispatched = await worker.evaluate(
      async ({ srcUrl, pageUrl }) => {
        const [tab] = await chrome.tabs.query({ url: pageUrl })
        const ev = chrome.contextMenus.onClicked as unknown as { dispatch?: (...a: unknown[]) => void }
        if (typeof ev.dispatch !== 'function') return 'no-dispatch'
        ev.dispatch({ menuItemId: 'add-image', srcUrl, pageUrl, editable: false, mediaType: 'image' }, tab)
        return 'ok'
      },
      { srcUrl, pageUrl: gallery.url() },
    )
    expect(dispatched).toBe('ok')
  })

  await test.step('the item appears on the board', async () => {
    await expect
      .poll(async () => (await boardItems(board.id)).filter((i) => i.kind === 'image').length, { timeout: 20_000 })
      .toBe(1)
    const [item] = await boardItems(board.id)
    expect(item.page_url).toBe(`${SITE_URL}/gallery.html`)
    await expectItemCount(app, 1)
    await expect(itemButton(app, /^image /)).toBeAttached()
    // the extension's badge reports success
    await expect
      .poll(() => worker.evaluate(() => chrome.action.getBadgeText({})))
      .toBe('OK')
  })
})
