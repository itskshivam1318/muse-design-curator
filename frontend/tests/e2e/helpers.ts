import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { expect, type Locator, type Page } from '@playwright/test'
import { API_URL } from './ports.ts'

/** Files written by backend/scripts/e2e_prepare.py (also served by the fixture site). */
export const SITE_DIR = resolve(import.meta.dirname, '../../../data/e2e/site')
export const sitePath = (name: string) => join(SITE_DIR, name)

export interface ApiItem {
  id: string
  kind: string
  role: string
  parse_status: string
  original_filename: string | null
  page_title: string | null
  page_url: string | null
  parent_item_id: string | null
  x: number
  y: number
  w: number
  h: number
  note_text?: string | null
  /** A rendered result not yet kept: listed, but not on the canvas. */
  staged?: boolean
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api${path}`, init)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

export const boardItems = (boardId: string) =>
  apiJson<{ items: ApiItem[] }>(`/boards/${boardId}/items`).then((r) => r.items)

export function boardIdOf(page: Page): string {
  const m = /\/boards\/([^/?#]+)/.exec(page.url())
  if (!m) throw new Error(`not on a board page: ${page.url()}`)
  return decodeURIComponent(m[1])
}

/** The canvas region announces its item count in its accessible name. */
export const canvas = (page: Page) => page.getByRole('region', { name: /^Board canvas/ })

export async function expectItemCount(page: Page, n: number): Promise<void> {
  await expect(canvas(page)).toHaveAccessibleName(new RegExp(`^Board canvas, ${n} items?,`))
}

/** The screen-reader list mirrors every canvas item; its buttons select them (keyboard path). */
export function itemButton(page: Page, name: string | RegExp): Locator {
  return page.getByRole('list', { name: 'Items on this board' }).getByRole('button', { name })
}

export async function selectItem(page: Page, name: string | RegExp): Promise<void> {
  const btn = itemButton(page, name)
  await btn.focus()
  await page.keyboard.press('Enter')
  await expect(btn).toHaveAttribute('aria-pressed', 'true')
}

/** Simulate dropping files from the desktop onto the canvas (a real DataTransfer with File objects). */
export async function dropFiles(page: Page, target: Locator, paths: string[], mime = 'image/jpeg'): Promise<void> {
  const files = paths.map((p) => ({ name: p.split('/').pop()!, b64: readFileSync(p).toString('base64') }))
  const dataTransfer = await page.evaluateHandle(
    ({ files, mime }) => {
      const dt = new DataTransfer()
      for (const f of files) {
        const bytes = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0))
        dt.items.add(new File([bytes], f.name, { type: mime }))
      }
      return dt
    },
    { files, mime },
  )
  const box = await target.boundingBox()
  const at = box ? { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 } : {}
  await target.dispatchEvent('dragover', { dataTransfer, ...at })
  await target.dispatchEvent('drop', { dataTransfer, ...at })
}

/** Open the Library rail panel: upload, link and extension pairing live there. */
export async function openLibrary(page: Page): Promise<void> {
  const btn = page.getByRole('button', { name: /^Library/ })
  if ((await btn.getAttribute('aria-pressed')) !== 'true') await btn.click()
  await expect(page.getByRole('group', { name: 'Add to board' })).toBeVisible()
}

/** Create a board and (optionally) set its context sentence. */
export async function createBoard(page: Page, title: string, context?: string): Promise<string> {
  await page.goto('/')
  await page.getByLabel('New board').fill(title)
  await page.getByRole('button', { name: 'Create board' }).click()
  await expect(page).toHaveURL(/\/boards\/brd_/)
  const boardId = boardIdOf(page)
  if (context) {
    const bar = page.getByRole('region', { name: 'Board context' })
    await bar.getByRole('button', { name: /Say what it's for/ }).click()
    await bar.getByLabel('What is this board for?').fill(context)
    await bar.getByRole('button', { name: 'Save' }).click()
  }
  return boardId
}

/** Close the Library panel (it covers the left of the board). */
export async function closeLibrary(page: Page): Promise<void> {
  const btn = page.getByRole('button', { name: /^Library/ })
  if ((await btn.getAttribute('aria-pressed')) === 'true') await btn.click()
  await expect(page.getByRole('dialog', { name: 'Library' })).toHaveCount(0)
}

/** Escape a string for use inside a RegExp. */
export const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// ---- the exploration map: callouts, flowers, petal cards ----

/** A part's callout card (or "Whole item") around the selected item. */
export const callout = (page: Page, name: string) => page.locator('.callout-layer').getByRole('group', { name, exact: true })
export const flower = (page: Page, name: string) => page.getByRole('group', { name: `${name} flower`, exact: true })
export const petals = (f: Locator) => f.getByTestId('petal')

/** Click a dimension on the selected item's callouts and wait for its (new) flower. */
export async function openDimension(page: Page, dimension: string): Promise<Locator> {
  const named = flower(page, dimension)
  const before = new Set(await named.evaluateAll((els) => els.map((e) => e.getAttribute('data-exploration-id'))))
  await page.locator('.callout-layer').getByRole('button', { name: new RegExp(`^${escapeRe(dimension)} ·`) }).click()
  let id: string | null | undefined
  await expect
    .poll(async () => {
      const ids = await named.evaluateAll((els) => els.map((e) => e.getAttribute('data-exploration-id')))
      id = ids.find((x) => !before.has(x))
      return id
    })
    .toBeTruthy()
  const f = page.locator(`[data-exploration-id="${id}"]`)
  // the group itself has no box: its hub and petals are placed in canvas units
  await expect(f.locator('.flower-hub')).toBeVisible()
  await expect(petals(f).first()).toBeVisible()
  return f
}

/** At most this many renders (and "More like this" batches) before renderUntilOk gives up. */
const MAX_RENDERS = 16
const MAX_MORE = 2

/**
 * Open each petal in turn and render it until one's check reads ✓; returns that petal's card. The
 * mock answers "yes" for about a third of prompts, so "More like this" brings new options if needed.
 * Bounded: fails after MAX_RENDERS renders or MAX_MORE batches, naming every check it read.
 */
export async function renderUntilOk(page: Page, f: Locator, renderTitle: string, renderDetail: string): Promise<Locator> {
  const tried: string[] = []
  let more = 0
  const giveUp = (why: string) =>
    new Error(`renderUntilOk: ${why}; ${tried.length} render(s) without a ✓ check: ${tried.join(' | ') || 'none'}`)
  for (let i = 0; tried.length < MAX_RENDERS; i++) {
    const n = await petals(f).count()
    if (i >= n) throw giveUp(`ran out of petals at ${n}`)
    const petal = petals(f).nth(i)
    if ((await petal.getAttribute('aria-label'))?.match(/ · (rendered|drifted|kept)$/)) continue
    const optionId = (await petal.getAttribute('data-option-id'))!
    await petal.click()
    const card = page.locator('.petal-card')
    await expect(card).toBeVisible()
    const render = card.getByRole('button', { name: new RegExp(`^${escapeRe(renderTitle)}`) })
    await expect(render.locator('.petal-render-title')).toHaveText(renderTitle)
    await expect(render.locator('.petal-render-detail')).toHaveText(renderDetail)
    await render.click()
    const check = card.locator('.petal-check')
    await expect(check).toBeVisible({ timeout: 30_000 })
    await expect(check).not.toHaveText('Checking…', { timeout: 30_000 })
    const text = (await check.textContent()) ?? ''
    if (text.startsWith('✓')) return card
    tried.push(`${await card.locator('.petal-card-name').textContent()}: ${text}`)
    // close the card (its petal toggles it; it may cover the next petal) and try the next one;
    // past the last, ask for more options
    await expect(f.locator(`[data-option-id="${optionId}"]`)).toHaveAttribute('aria-label', / · (rendered|drifted)$/)
    if (i === n - 1) {
      if (more === MAX_MORE) throw giveUp(`asked for more options ${MAX_MORE} times`)
      more += 1
      await card.getByRole('button', { name: 'More like this' }).click()
      await expect(petals(f)).toHaveCount(n + 8)
    }
    await petal.click()
    await expect(card).toHaveCount(0)
  }
  throw giveUp(`stopped at ${MAX_RENDERS} renders`)
}

/** Pan the view so the flower's hub sits in the upper left of the canvas, clear of the agent card. */
export async function panToReach(page: Page, f: Locator): Promise<void> {
  const c = (await canvas(page).boundingBox())!
  const hub = (await f.locator('.flower-hub').boundingBox())!
  await page.mouse.move(c.x + 20, c.y + c.height / 2)
  await page.mouse.wheel(hub.x - (c.x + c.width * 0.3), hub.y - (c.y + c.height * 0.3))
  await expect
    .poll(async () => (await f.locator('.flower-hub').boundingBox())!.y)
    .toBeLessThan(c.y + c.height * 0.4)
}
