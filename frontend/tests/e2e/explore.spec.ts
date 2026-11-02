import { expect, test } from '@playwright/test'
import {
  boardItems,
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

/**
 * Explore -> render on mock providers: a dimension on a callout opens a flower of note petals (the
 * mock reasoning provider names them like "Option A 3f2c"); a petal renders with Muse Image (the
 * mock image model id is "mock-image") and a kept result is an ordinary item with a verdict.
 */
test('explore option then render', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E explore', 'A field watch for a 38 mm wrist.')
  await openLibrary(page)
  await page
    .getByLabel('Choose images or video to upload')
    .setInputFiles(['watch_01.jpg', 'watch_02.jpg', 'watch_03.jpg', 'watch_04.jpg', 'watch_05.jpg'].map(sitePath))
  await expectItemCount(page, 5)
  await expect(page.getByRole('complementary', { name: 'Board signals' }).getByText('Watch lens · curated')).toBeVisible()
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)
  await closeLibrary(page)

  await selectItem(page, /^image watch_01\.jpg/)
  const f = await openDimension(page, 'Body colour')
  expect(await f.getByTestId('petal').count()).toBeGreaterThanOrEqual(6) // one note petal per option

  const knownIds = new Set((await boardItems(boardId)).map((i) => i.id))
  await panToReach(page, f)
  const card = await renderUntilOk(page, f, 'Generate image', 'Muse Image · inside the Body mask')
  // a result is a staged item: it shows on its petal and card, not yet on the board
  await expect(card.locator('img.petal-img')).toBeVisible()
  await expectItemCount(page, 5)
  await card.getByRole('button', { name: 'Keep', exact: true }).click()
  await expectItemCount(page, 6)

  // the kept result: find it by id and check its caption and verdict
  let generatedId = ''
  await expect
    .poll(async () => {
      generatedId =
        (await boardItems(boardId)).find((i) => !knownIds.has(i.id) && i.parent_item_id && !i.staged)?.id ?? ''
      return generatedId
    })
    .not.toBe('')
  const gen = (await boardItems(boardId)).find((i) => i.id === generatedId)!
  const label = gen.original_filename ?? gen.page_title ?? gen.page_url ?? gen.id
  await page.keyboard.press('Escape')
  await selectItem(page, new RegExp(escapeRe(label)))
  await expect(page.getByRole('note', { name: 'Generated image' })).toHaveText('generated · mock-image', { timeout: 10_000 })
  await expect(page.locator('.credit-caption .verdict')).toBeVisible()
  await expect(page.locator('.credit-caption .verdict')).not.toHaveText('Checking…', { timeout: 15_000 })
})
