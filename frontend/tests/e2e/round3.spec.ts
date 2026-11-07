import { expect, test, type Page } from '@playwright/test'
import {
  apiJson,
  boardItems,
  closeLibrary,
  createBoard,
  expectItemCount,
  openLibrary,
  selectItem,
  sitePath,
  type ApiItem,
} from './helpers.ts'
import { API_URL } from './ports.ts'

/** Round 3 plugins on mock providers and a scripted mock fal (backend/scripts/e2e_server.py). */

interface OptionItem extends ApiItem {
  option_run_id?: string | null
}
interface NodeJson {
  id: string
  params: Record<string, unknown>
}

const GRID = 20 // distinct colourways of the fixture's three parts under the default palette

const items = (boardId: string) => boardItems(boardId) as Promise<OptionItem[]>
const options = async (boardId: string) => (await items(boardId)).filter((i) => i.option_run_id)

async function post<T>(path: string, body?: unknown): Promise<T> {
  return apiJson<T>(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

/** A board with one uploaded, fully analysed object. */
async function boardWithItem(page: Page, title: string): Promise<{ boardId: string; itemId: string }> {
  const boardId = await createBoard(page, title)
  await openLibrary(page)
  await page.getByLabel('Choose images or video to upload').setInputFiles([sitePath('object_large.jpg')])
  await expectItemCount(page, 1)
  await closeLibrary(page)
  await expect.poll(async () => (await items(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)
  return { boardId, itemId: (await items(boardId))[0].id }
}

/** Add a plugin to the board and place its node on the item (the node appears after a reload). */
async function placeNode(boardId: string, pluginId: string, itemId: string, x: number, y = 100): Promise<NodeJson> {
  await post(`/boards/${boardId}/plugins`, { plugin_id: pluginId })
  return post<NodeJson>(`/boards/${boardId}/nodes`, { plugin_id: pluginId, x, y, input_item_ids: [itemId] })
}

const patchParams = (node: NodeJson, params: Record<string, unknown>) =>
  apiJson(`/nodes/${node.id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ params: { ...node.params, ...params } }),
  })

const hash = async (id: string) => {
  const res = await fetch(`${API_URL}/api/items/${id}/image?size=full`)
  const bytes = new Uint8Array(await res.arrayBuffer())
  let h = 0
  for (const b of bytes) h = (h * 31 + b) >>> 0
  return `${bytes.length}:${h}`
}

test('variation: 24 options, shuffle, keep two, clear, undo', async ({ page }) => {
  const { boardId, itemId } = await boardWithItem(page, 'E2E variation')
  const node = await placeNode(boardId, 'recolor', itemId, 700)
  await patchParams(node, { count: 24, seed: 1 })
  await page.reload()
  const card = page.getByRole('group', { name: 'Variation node' })
  await expect(card).toBeVisible()

  await card.getByRole('button', { name: 'Run', exact: true }).click()
  // asks for 24; the mock-read item has three mask parts, so only GRID distinct colourways exist
  await expect.poll(async () => (await options(boardId)).length, { timeout: 90_000 }).toBe(GRID)
  await expectItemCount(page, GRID + 1)
  const run1 = await options(boardId)
  const run1Ids = new Set(run1.map((i) => i.id))
  const run1Hashes = await Promise.all(run1.map((i) => hash(i.id)))
  expect(new Set(run1Hashes).size).toBe(GRID) // every tile is its own colourway

  // Shuffle sets a new seed: running again lays out a different grid
  await card.locator('.node-summary').click()
  await card.getByRole('button', { name: 'Shuffle' }).click()
  await card.locator('.node-summary').click() // fold the settings so the card clears the dock
  await card.getByRole('button', { name: 'Run again' }).click()
  await expect
    .poll(async () => (await options(boardId)).filter((i) => !run1Ids.has(i.id)).length, { timeout: 90_000 })
    .toBe(GRID)
  const run2 = (await options(boardId)).filter((i) => !run1Ids.has(i.id))
  const run2Hashes = await Promise.all(run2.map((i) => hash(i.id)))
  expect(run2Hashes[0]).not.toBe(run1Hashes[0]) // a different first tile
  expect([...run2Hashes].sort()).not.toEqual([...run1Hashes].sort()) // and a different set of tiles

  // keep two (Keep makes them ordinary items), then Clear drops the rest of the latest run's
  // options; the earlier run's grid is left alone
  const [a, b] = [run2[0], run2[1]]
  await post(`/items/${a.id}/keep-option`)
  await post(`/items/${b.id}/keep-option`)
  await page.reload()
  await card.getByRole('button', { name: /^Clear options/ }).click()
  await expect.poll(async () => (await options(boardId)).length).toBe(GRID)
  expect((await options(boardId)).every((i) => run1Ids.has(i.id))).toBe(true)
  await expect.poll(async () => (await items(boardId)).length).toBe(3 + GRID)
  await expectItemCount(page, 3 + GRID)

  // undo: restore brings a cleared option back
  const gone = run2[5]
  await post(`/items/${gone.id}/restore`)
  await expect.poll(async () => (await options(boardId)).length).toBe(GRID + 1)
})

test('clean-up: one cut-out lands on the board', async ({ page }) => {
  const { boardId, itemId } = await boardWithItem(page, 'E2E clean-up')
  await placeNode(boardId, 'cleanup', itemId, 700)
  await page.reload()
  const card = page.getByRole('group', { name: 'Clean-up node' })
  await card.getByRole('button', { name: 'Run', exact: true }).click()
  await expect.poll(async () => (await items(boardId)).length, { timeout: 60_000 }).toBe(2)
  await expect(card.getByRole('list', { name: 'Generated' }).getByRole('listitem')).toHaveCount(1)
  await expectItemCount(page, 2)
})

test('3D and Animate: a model opens the viewer, a video plays', async ({ page }) => {
  const { boardId, itemId } = await boardWithItem(page, 'E2E fal')
  await placeNode(boardId, 'mesh', itemId, 700)
  const clipNode = await placeNode(boardId, 'video', itemId, 700, 500)
  await patchParams(clipNode, { prompt: 'a slow turn' })
  await page.reload()

  const mesh = page.getByRole('group', { name: /Image → 3D node/ })
  await mesh.getByRole('button', { name: 'Run', exact: true }).click()
  await expect.poll(async () => (await items(boardId)).some((i) => i.kind === 'model'), { timeout: 60_000 }).toBe(true)
  await selectItem(page, /^model /)
  await page.getByRole('toolbar', { name: 'Item actions' }).getByRole('button', { name: 'Open 3D' }).click()
  const viewer = page.getByRole('dialog', { name: '3D viewer' })
  await expect(viewer).toBeVisible()
  await expect(viewer.getByText('Download .glb')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)

  const video = page.getByRole('group', { name: 'Video node' })
  await video.getByRole('button', { name: 'Run', exact: true }).click()
  await expect.poll(async () => (await items(boardId)).some((i) => i.kind === 'video'), { timeout: 60_000 }).toBe(true)
  const clip = (await items(boardId)).find((i) => i.kind === 'video')!
  const res = await fetch(`${API_URL}/api/items/${clip.id}/video`)
  expect(res.status).toBe(200)
  expect(res.headers.get('content-type')).toMatch(/^video\//)
  // click the clip on the canvas: the inline player opens and plays
  await selectItem(page, /^video /)
  const bar = await page.getByRole('toolbar', { name: 'Item actions' }).boundingBox()
  const player = page.getByLabel('Video playing; click to pause')
  // the clip sits just under its toolbar: step down until the click lands on it
  for (let dy = 30; dy <= 150 && !(await player.isVisible()); dy += 20) {
    await page.mouse.click(bar!.x + bar!.width / 2, bar!.y + bar!.height + dy)
    await page.waitForTimeout(250)
  }
  await expect(player).toBeVisible()
  // the bundled headless Chromium has no H.264 decoder, so assert the player is wired to the clip, not frames
  await expect(player).toHaveAttribute('src', new RegExp(`/api/items/${clip.id}/video`))
})

test('without a fal key, 3D and Animate show not connected', async ({ page }) => {
  // the e2e backend is connected to a mock fal; the catalog the page reads is told otherwise
  await page.route('**/api/plugins', async (route) => {
    const res = await route.fetch()
    const body = (await res.json()) as { plugins: { id: string; status: string }[] }
    for (const p of body.plugins) if (p.id === 'mesh' || p.id === 'video') p.status = 'not_connected'
    await route.fulfill({ response: res, json: body })
  })
  const { boardId, itemId } = await boardWithItem(page, 'E2E not connected')
  await placeNode(boardId, 'mesh', itemId, 700)
  await placeNode(boardId, 'video', itemId, 700, 500)
  await page.reload()
  for (const name of [/Image → 3D node/, 'Video node']) {
    const card = page.getByRole('group', { name })
    await expect(card.getByText(/not connected/)).toBeVisible()
    await expect(card.getByRole('button', { name: 'Run', exact: true })).toBeDisabled()
  }
  expect(await items(boardId)).toHaveLength(1)
})
