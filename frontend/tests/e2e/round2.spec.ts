import { expect, test } from '@playwright/test'
import {
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
  renderUntilOk,
  selectItem,
  sitePath,
} from './helpers.ts'

/** Notes, flowers and plugins on mock providers (the mock image model id is "mock-image"). */

test('note: write, visualize, a generated image appears beside it', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E note')
  const text = 'Strap in waxed canvas, dark olive'

  const box = (await canvas(page).boundingBox())!
  const at = { x: box.x + box.width * 0.4, y: box.y + box.height * 0.35 }
  await canvas(page).focus()
  await page.keyboard.press('n')
  await page.mouse.click(at.x, at.y)
  const editor = page.getByLabel('Note', { exact: true })
  await expect(editor).toBeFocused()
  await editor.fill(text)
  await page.keyboard.press('Escape')
  await expect(editor).toHaveCount(0)

  // the note is created on save
  await expect.poll(async () => (await boardItems(boardId)).filter((i) => i.kind === 'note').length).toBe(1)
  await expectItemCount(page, 1)

  // a selected note shows its bar (hovering works too, but the board's first fit can move the note
  // out from under a fixed mouse position)
  await selectItem(page, /^note /)
  const bar = page.getByRole('toolbar', { name: 'Note actions' })
  await expect(bar).toBeVisible()
  await bar.getByRole('button', { name: 'Visualize' }).click()

  await expect.poll(async () => (await boardItems(boardId)).filter((i) => i.parent_item_id).length, { timeout: 20_000 }).toBe(1)
  await expectItemCount(page, 2)
  const gen = (await boardItems(boardId)).find((i) => i.parent_item_id)!
  await page.mouse.move(5, 5)
  await selectItem(page, new RegExp(`^image .*${escapeRe(gen.original_filename ?? gen.page_title ?? gen.id)}`))
  await expect(page.getByRole('note', { name: 'Generated image' })).toHaveText('generated · mock-image', { timeout: 10_000 })
})

test('flower: render, keep, reload, branch from the kept result', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E flower keep')
  await openLibrary(page)
  await page.getByLabel('Choose images or video to upload').setInputFiles([sitePath('watch_01.jpg')])
  await expectItemCount(page, 1)
  await closeLibrary(page)
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)

  await selectItem(page, /^image watch_01\.jpg/)
  const f = await openDimension(page, 'Detail style')
  await panToReach(page, f)
  const card = await renderUntilOk(page, f, 'Generate image', 'Muse Image · inside the Detail mask')
  const optionId = (await f.locator('.petal.is-open').getAttribute('data-option-id'))!
  await card.getByRole('button', { name: 'Keep', exact: true }).click()
  await expectItemCount(page, 2)
  // a kept option has no petal: its take is docked in the ring (an ordinary item) and the hub counts it
  const kept = () => page.locator(`[data-testid="petal"][data-option-id="${optionId}"]`)
  await expect(kept()).toHaveCount(0)
  await expect(f.locator('.flower-hub')).toContainText('1 kept')
  await expect(page.locator('.petal.is-kept')).toHaveCount(0)

  await page.reload()
  await expectItemCount(page, 2)
  await expect(f.locator('.flower-hub')).toContainText('1 kept')
  await expect(kept()).toHaveCount(0)

  // the docked take is selected like any item: its own callouts open from there
  const keptItem = (await boardItems(boardId)).find((i) => i.parent_item_id && !i.staged)!
  await page.mouse.move(5, 5)
  await selectItem(page, new RegExp(`^image .*${escapeRe(keptItem.original_filename ?? keptItem.page_title ?? keptItem.id)}`))
  await expect(callout(page, 'Detail')).toBeVisible()
})

test('plugin: add Palette & material, run on an image, a Palette note lands on the board', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E plugin')
  await openLibrary(page)
  await page.getByLabel('Choose images or video to upload').setInputFiles([sitePath('watch_01.jpg')])
  await expectItemCount(page, 1)
  // the palette plugin reads pixels, not attributes: it does not wait for the lens-gated parse
  await closeLibrary(page)

  // add the plugin from the Plugins rail panel
  await page.getByRole('button', { name: 'Plugins', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'Plugins' })
  await expect(panel).toBeVisible()
  await panel.getByRole('navigation', { name: 'Packs' }).getByRole('button', { name: /^All plugins/ }).click() // packs are only suggestions
  const add = panel.getByRole('button', { name: 'Add Palette & material' })
  await add.click()
  await expect(panel.getByRole('button', { name: 'Added Palette & material' })).toBeVisible()
  await page.getByRole('button', { name: 'Plugins', exact: true }).click()
  await expect(panel).toHaveCount(0)

  // select the image, then place a node from the Nodes menu: it takes the selection as input
  await selectItem(page, /^image watch_01\.jpg/)
  await page.getByRole('button', { name: 'Nodes', exact: true }).click()
  await page.getByRole('dialog', { name: 'Nodes' }).getByRole('button', { name: /Palette & material/ }).click()
  const node = page.getByRole('group', { name: 'Palette & material node' })
  await expect(node).toBeVisible()
  await expect(node.getByRole('list', { name: 'Inputs' })).toBeVisible()

  await node.getByRole('button', { name: 'Run', exact: true }).click()

  // the run finishes over SSE: a note starting "Palette:" lands on the board and the card shows done
  await expect
    .poll(
      async () =>
        (await boardItems(boardId)).some((i) => i.kind === 'note' && i.note_text?.startsWith('Palette:')),
      { timeout: 30_000 },
    )
    .toBe(true)
  await expect(node.getByText(/1 note added to the board/)).toBeVisible({ timeout: 15_000 })
  await expect(node.getByRole('button', { name: 'Run again' })).toBeEnabled()
  await expectItemCount(page, 2)
  await expect(page.getByRole('list', { name: 'Items on this board' }).getByRole('button', { name: /^note Palette:/ })).toBeVisible()
})
