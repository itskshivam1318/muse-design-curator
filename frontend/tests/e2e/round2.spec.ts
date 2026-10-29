import { expect, test } from '@playwright/test'
import { boardItems, canvas, createBoard, expectItemCount, openLibrary, selectItem, sitePath } from './helpers.ts'

/** Notes and the axis on mock providers (the mock image model id is "mock-image"). */

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

  // hover the note to reveal its bar
  await page.mouse.move(at.x + 40, at.y + 20)
  const bar = page.getByRole('toolbar', { name: 'Note actions' })
  await expect(bar).toBeVisible()
  await bar.getByRole('button', { name: 'Visualize' }).click()

  await expect.poll(async () => (await boardItems(boardId)).filter((i) => i.parent_item_id).length, { timeout: 20_000 }).toBe(1)
  await expectItemCount(page, 2)
  const gen = (await boardItems(boardId)).find((i) => i.parent_item_id)!
  await page.mouse.move(5, 5)
  await selectItem(page, new RegExp(`^image .*${gen.original_filename ?? gen.page_title ?? gen.id}`))
  await expect(page.getByRole('note', { name: 'Generated image' })).toHaveText('generated · mock-image', { timeout: 10_000 })
})

test('axis: visualize, regenerate, keep, reload, un-keep', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E axis', 'A field watch for a 38 mm wrist.')
  await openLibrary(page)
  await page
    .getByLabel('Choose images or video to upload')
    .setInputFiles(['watch_01.jpg', 'watch_02.jpg', 'watch_03.jpg', 'watch_04.jpg', 'watch_05.jpg'].map(sitePath))
  await expectItemCount(page, 5)
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)

  await selectItem(page, /^image watch_01\.jpg/)
  await page.keyboard.press('a')
  await page.getByRole('dialog', { name: 'Pick an attribute to explore' }).getByRole('button').first().click()

  const cards = page.getByTestId('axis-card')
  await expect(cards.first()).toBeVisible({ timeout: 30_000 })
  const optionId = (await cards.first().getAttribute('data-option-id'))!
  const card = page.locator(`[data-testid="axis-card"][data-option-id="${optionId}"]`)
  const name = (await card.locator('.axis-card-name').textContent())!.trim()

  await card.click()
  const pop = page.getByRole('dialog', { name })
  await pop.getByRole('button', { name: 'Visualize', exact: true }).click()
  await expect(pop.getByRole('img', { name: `${name} · take 1` })).toBeVisible({ timeout: 15_000 })

  await pop.getByRole('button', { name: 'Regenerate' }).click()
  await expect(pop.getByRole('img', { name: `${name} · take 2` })).toBeVisible({ timeout: 15_000 })

  await pop.getByRole('button', { name: 'Keep', exact: true }).click()
  await expect(card).toContainText('· kept')
  await expectItemCount(page, 6)

  await page.reload()
  await expectItemCount(page, 6)
  await expect(page.locator(`[data-testid="axis-card"][data-option-id="${optionId}"]`)).toContainText('· kept')

  // a kept card selects its item and opens the popover with Un-keep
  await page.locator(`[data-testid="axis-card"][data-option-id="${optionId}"]`).click()
  await page.getByRole('button', { name: 'Un-keep' }).click()
  const back = page.locator(`[data-testid="axis-card"][data-option-id="${optionId}"]`)
  await expect(back).not.toContainText('· kept')
  await expect(back.locator('.axis-card-name')).toHaveText(name)
  await expectItemCount(page, 5)
})
