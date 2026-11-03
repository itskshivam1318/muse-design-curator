import { createHash } from 'node:crypto'
import { expect, type Page, test } from '@playwright/test'
import { API_URL } from './ports.ts'
import {
  type ApiItem,
  apiJson,
  boardItems,
  closeLibrary,
  createBoard,
  expectItemCount,
  openLibrary,
  selectItem,
  sitePath,
} from './helpers.ts'

/**
 * "Put into" on mock providers: connect one photo to another, aim at a part, put it in. The mock
 * analysis gives a photo the parts Body and Detail (no two of a kind), so a part aimed at is 1 spot.
 */

type PutItem = ApiItem & { sha256: string | null; put_source_item_id: string | null }
const items = (boardId: string) => boardItems(boardId) as Promise<PutItem[]>

/** The full image's bytes, hashed: what is stored, not what the record says. */
async function imageSha(id: string): Promise<string> {
  const res = await fetch(`${API_URL}/api/items/${encodeURIComponent(id)}/image?size=full`)
  expect(res.ok).toBe(true)
  return createHash('sha256').update(Buffer.from(await res.arrayBuffer())).digest('hex')
}

/** An item's drawn box on screen (its Konva node, offset by the stage's place on the page). */
async function screenBox(page: Page, id: string) {
  return page.evaluate((id) => {
    const K = (window as unknown as { Konva: { stages: { findOne: (s: string) => { getClientRect: () => DOMRect } | undefined; container: () => HTMLElement }[] } }).Konva
    for (const stage of K.stages) {
      const node = stage.findOne(`#${id}`)
      if (!node) continue
      const r = node.getClientRect()
      const c = stage.container().getBoundingClientRect()
      return { x: c.left + r.x, y: c.top + r.y, width: r.width, height: r.height }
    }
    return null
  }, id)
}

test('put into: connect a photo to another, aim at a part, put it in', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E put into')
  await openLibrary(page)
  await page.getByLabel('Choose images or video to upload').setInputFiles([sitePath('watch_01.jpg'), sitePath('watch_02.jpg')])
  await expectItemCount(page, 2)
  await closeLibrary(page)
  await expect.poll(async () => (await items(boardId)).every((i) => i.parse_status === 'completed'), { timeout: 30_000 }).toBe(true)

  const before = await items(boardId)
  const source = before.find((i) => i.original_filename === 'watch_01.jpg')!
  const target = before.find((i) => i.original_filename === 'watch_02.jpg')!
  const shas = { source: await imageSha(source.id), target: await imageSha(target.id) }
  // the mock analysis gives a mask part no rough box: it gets one the first time SAM finds it (as when
  // its callout is hovered); load the board again so the target's parts are read with their boxes
  await apiJson(`/items/${encodeURIComponent(target.id)}/parts/body/region`)
  await apiJson(`/items/${encodeURIComponent(target.id)}/parts/detail/region`)
  await page.reload()
  await expectItemCount(page, 2)

  await selectItem(page, /^image watch_01\.jpg/)
  const dot = page.getByLabel('Connect to another picture')
  await expect(dot).toBeVisible()
  const d = (await dot.boundingBox())!
  const t = (await screenBox(page, target.id))!
  expect(t).toBeTruthy()
  // the Body part covers the picture's middle
  const aim = { x: t.x + t.width / 2, y: t.y + t.height / 2 }

  await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2)
  await page.mouse.down()
  await page.mouse.move((d.x + aim.x) / 2, (d.y + aim.y) / 2, { steps: 5 })
  await page.mouse.move(aim.x, aim.y, { steps: 5 })
  await expect(page.locator('.put-line')).toBeVisible()
  await expect(page.locator('.put-count')).toHaveText('1 spot')
  await page.mouse.up()

  const words = page.getByPlaceholder('Anything to add? (optional)')
  await expect(words).toBeVisible()
  await expect(page.locator('.put-card-anchor')).toContainText('Body')
  await words.fill('keep the blur')
  await page.getByRole('button', { name: 'Put in', exact: true }).click()

  // a ghost holds the result's place, then the result replaces it
  await expect(page.getByText('Putting in…')).toBeVisible()
  let made: PutItem | undefined
  await expect
    .poll(async () => {
      made = (await items(boardId)).find((i) => !before.some((b) => b.id === i.id))
      return made?.id
    }, { timeout: 30_000 })
    .toBeTruthy()
  expect(made!.put_source_item_id).toBe(source.id)
  expect(made!.parent_item_id).toBe(target.id)
  await expect(page.getByText('Putting in…')).toHaveCount(0)
  await expectItemCount(page, 3)

  // the two originals are untouched
  expect(await imageSha(source.id)).toBe(shas.source)
  expect(await imageSha(target.id)).toBe(shas.target)
  const after = await items(boardId)
  expect(after.find((i) => i.id === source.id)!.sha256).toBe(source.sha256)
  expect(after.find((i) => i.id === target.id)!.sha256).toBe(target.sha256)
})
