import { expect, type Locator, type Page, test } from '@playwright/test'
import {
  type ApiItem,
  boardItems,
  callout,
  canvas,
  closeLibrary,
  createBoard,
  escapeRe,
  expectItemCount,
  openDimension,
  openLibrary,
  panToReach,
  petals,
  renderUntilOk,
  selectItem,
  sitePath,
} from './helpers.ts'

/**
 * The exploration map on mock providers. The mock analysis gives a photo the parts Body and Detail
 * (masks) with Body colour / Detail style on them and Subject / Medium on the whole item; a screen
 * at least 1.6 wide the parts Header and Primary button (boxes); a note the passage Opening with Tone
 * and Length on the whole item. Mock option names are "Option A 3f2c" and so on. Whether a result's
 * check reads ✓ is a hash of its prompt, so the specs try petals until one does.
 */

type Box = { x: number; y: number; width: number; height: number }

const label = (i: ApiItem) => i.original_filename ?? i.page_title ?? i.page_url ?? i.id
async function boardWith(page: Page, title: string, files: string[]): Promise<string> {
  const boardId = await createBoard(page, title)
  await openLibrary(page)
  await page.getByLabel('Choose images or video to upload').setInputFiles(files.map(sitePath))
  await expectItemCount(page, files.length)
  await closeLibrary(page)
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed'), { timeout: 30_000 }).toBe(true)
  return boardId
}

/** A flower's drawn extent on screen: its hub and every petal. */
async function flowerBox(f: Locator): Promise<Box> {
  const boxes = [await f.locator('.flower-hub').boundingBox()]
  for (const p of await petals(f).all()) boxes.push(await p.boundingBox())
  const bs = boxes.filter((b): b is Box => !!b)
  const x = Math.min(...bs.map((b) => b.x))
  const y = Math.min(...bs.map((b) => b.y))
  return {
    x,
    y,
    width: Math.max(...bs.map((b) => b.x + b.width)) - x,
    height: Math.max(...bs.map((b) => b.y + b.height)) - y,
  }
}

const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

/** The hub's place in canvas units (its style): unaffected by panning or zooming the view. */
const hubAt = (f: Locator) => f.locator('.flower-hub').evaluate((el: HTMLElement) => `${el.style.left},${el.style.top}`)

test('callouts: parts, the whole item, and the hovered region', async ({ page }) => {
  await boardWith(page, 'E2E callouts', ['watch_01.jpg'])
  await selectItem(page, /^image watch_01\.jpg/)
  await expect(callout(page, 'Body')).toBeVisible()
  await expect(callout(page, 'Detail')).toBeVisible()
  await expect(callout(page, 'Whole item')).toBeVisible()
  await expect(callout(page, 'Body')).toContainText('SAM mask')
  await expect(page.getByTestId('region-overlay')).toHaveCount(0)
  await callout(page, 'Body').hover()
  await expect(page.getByTestId('region-overlay')).toBeVisible()
  await expect(page.getByTestId('region-overlay')).toHaveAttribute('data-state', 'mask')
})

test('flower: note petals, render one inside the mask, keep it as an item', async ({ page }) => {
  const boardId = await boardWith(page, 'E2E flower', ['watch_01.jpg'])
  const before = await boardItems(boardId)
  await selectItem(page, /^image watch_01\.jpg/)
  const f = await openDimension(page, 'Body colour')
  await expect(f.locator('.flower-hub')).toContainText('Body colour')
  // petals are notes: nothing is rendered until asked
  expect(await petals(f).count()).toBeGreaterThanOrEqual(6)
  await expect(f.locator('img')).toHaveCount(0)
  for (const p of await petals(f).all()) await expect(p).not.toHaveAttribute('aria-label', / · (rendered|drifted|kept)$/)
  expect((await boardItems(boardId)).length).toBe(before.length)

  await panToReach(page, f)
  const card = await renderUntilOk(page, f, 'Generate image', 'Muse Image · inside the Body mask')
  await expect(card.locator('img.petal-img')).toBeVisible()
  await expect(card.locator('.petal-check')).toContainText('✓')
  await card.getByRole('button', { name: 'Keep', exact: true }).click()
  await expectItemCount(page, 2)

  let kept: ApiItem | undefined
  await expect
    .poll(async () => {
      // rendered results are staged items until kept
      kept = (await boardItems(boardId)).find((i) => !before.some((b) => b.id === i.id) && !i.staged)
      return kept?.id
    })
    .toBeTruthy()
  await expect(f.getByTestId('petal').filter({ has: page.locator('img') }).first()).toBeVisible()
  await page.keyboard.press('Escape')
  await selectItem(page, new RegExp(`^image .*${escapeRe(label(kept!))}`))
  await expect(callout(page, 'Body')).toBeVisible({ timeout: 30_000 })
  await expect(callout(page, 'Whole item')).toBeVisible()
})

test('three flowers: no overlap, nothing moves', async ({ page }) => {
  const boardId = await boardWith(page, 'E2E three flowers', ['watch_01.jpg', 'watch_02.jpg'])
  const positions = async () => (await boardItems(boardId)).map((i) => `${i.id}:${i.x},${i.y}`).sort()
  const placed = await positions()

  await selectItem(page, /^image watch_01\.jpg/)
  const first = await openDimension(page, 'Body colour')
  const hub = await hubAt(first)
  const second = await openDimension(page, 'Detail style')
  await page.keyboard.press('Escape')
  await selectItem(page, /^image watch_02\.jpg/)
  const third = await openDimension(page, 'Body colour')
  await page.keyboard.press('Escape')
  await expect(page.locator('.flower-hub')).toHaveCount(3)

  // zoom out until all three are on screen, then compare what is drawn
  await page.keyboard.press('f')
  const flowers = page.locator('.flower-layer [role="group"][aria-label$=" flower"]')
  for (let i = 0; i < 6 && (await flowers.count()) < 3; i++) {
    const c = (await canvas(page).boundingBox())!
    await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2)
    await page.keyboard.down('Control')
    await page.mouse.wheel(0, 300)
    await page.keyboard.up('Control')
  }
  await expect(flowers).toHaveCount(3)
  const boxes = [await flowerBox(first), await flowerBox(second), await flowerBox(third)]
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) expect(overlaps(boxes[i], boxes[j]), `flowers ${i} and ${j} overlap`).toBe(false)
  }
  expect(await hubAt(first)).toBe(hub)
  expect(await positions()).toEqual(placed)
})

test('extract a part: a linked child item with its own callouts', async ({ page }) => {
  const boardId = await boardWith(page, 'E2E extract', ['watch_01.jpg'])
  const source = (await boardItems(boardId))[0]
  await selectItem(page, /^image watch_01\.jpg/)
  await callout(page, 'Detail').getByRole('button', { name: 'Extract' }).click()
  await expectItemCount(page, 2)
  const child = (await boardItems(boardId)).find((i) => i.parent_item_id === source.id)!
  expect(child).toBeTruthy()
  expect(child.x).toBeGreaterThanOrEqual(source.x + source.w)
  await expect.poll(async () => (await boardItems(boardId)).find((i) => i.id === child.id)?.parse_status, { timeout: 30_000 }).toBe('completed')
  await page.keyboard.press('Escape')
  await selectItem(page, new RegExp(`^image .*${escapeRe(label(child))}`))
  await expect(callout(page, 'Body')).toBeVisible()
  await expect(callout(page, 'Whole item')).toBeVisible()
})

test('note: a passage part, rewrite only the passage, the change marked', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E passage')
  const text = 'Strap in waxed canvas, dark olive, with brass hardware that ages well'
  const box = (await canvas(page).boundingBox())!
  await canvas(page).focus()
  await page.keyboard.press('n')
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.35)
  const editor = page.getByLabel('Note', { exact: true })
  await expect(editor).toBeFocused()
  await editor.fill(text)
  await page.keyboard.press('Escape')
  await expect.poll(async () => (await boardItems(boardId)).find((i) => i.kind === 'note')?.parse_status, { timeout: 30_000 }).toBe('completed')

  await page.mouse.move(5, 5)
  await selectItem(page, /^note /)
  const passage = callout(page, 'Opening')
  await expect(passage).toBeVisible()
  // a note is an item: the "Getting started" steps are gone, nothing covers the callouts
  await expect(page.getByRole('region', { name: 'Getting started' })).toHaveCount(0)
  await expect(passage).toContainText('passage')
  await expect(callout(page, 'Whole item').getByRole('button', { name: /^Tone ·/ })).toBeVisible()

  // a dimension on the passage itself: its rewrite touches the passage only
  await passage.getByRole('button', { name: '+ Add dimension' }).click()
  await page.getByLabel('New dimension on Opening').fill('Warmth')
  await page.keyboard.press('Enter')
  const f = await openDimension(page, 'Warmth')
  const petal = petals(f).first()
  await petal.click()
  const card = page.locator('.petal-card')
  const render = card.getByRole('button', { name: /^Rewrite passage/ })
  await expect(render.locator('.petal-render-title')).toHaveText('Rewrite passage')
  await expect(render.locator('.petal-render-detail')).toHaveText('Muse Spark · this passage only')
  await render.click()
  // the mock rewrite upper-cases the passage (the first 40 characters): that span is marked
  const mark = card.locator('.petal-excerpt mark')
  await expect(mark).toBeVisible({ timeout: 30_000 })
  await expect(mark).toHaveText(/^[^a-z]+$/)
  await expect(card.locator('.petal-excerpt')).toContainText(text.slice(40))
})

test('wide screenshot: UI callouts with boxes', async ({ page }) => {
  await boardWith(page, 'E2E screen', ['screen.png'])
  await selectItem(page, /^image screen\.png/)
  await expect(callout(page, 'Header')).toContainText('box')
  await expect(callout(page, 'Primary button')).toContainText('box')
  await expect(callout(page, 'Body')).toHaveCount(0)
  await callout(page, 'Primary button').hover()
  await expect(page.getByTestId('region-overlay')).toHaveAttribute('data-state', 'box')
})
