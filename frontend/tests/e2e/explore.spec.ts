import { expect, test } from '@playwright/test'
import { boardItems, createBoard, expectItemCount, openLibrary, selectItem, sitePath } from './helpers.ts'

/**
 * Explore -> Visualize on mock providers: the mock reasoning provider returns eight options named
 * like "Option A 3f2c"; the mock image provider's model id is "mock-image".
 */
test('explore option then visualize', async ({ page }) => {
  const boardId = await createBoard(page, 'E2E explore', 'A field watch for a 38 mm wrist.')
  await openLibrary(page)
  await page
    .getByLabel('Choose images or video to upload')
    .setInputFiles(['watch_01.jpg', 'watch_02.jpg', 'watch_03.jpg', 'watch_04.jpg', 'watch_05.jpg'].map(sitePath))
  await expectItemCount(page, 5)
  await expect(page.getByRole('complementary', { name: 'Board signals' }).getByText('Watch lens · curated')).toBeVisible()
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)

  await selectItem(page, /^image watch_01\.jpg/)
  await page.keyboard.press('a') // the Axis tool
  await page.getByRole('dialog', { name: 'Pick an attribute to explore' }).getByRole('button').first().click()

  const cards = page.getByTestId('axis-card')
  await expect(cards.first()).toBeVisible({ timeout: 30_000 })
  const n = await cards.count()
  expect(n).toBeGreaterThanOrEqual(6)

  const knownIds = new Set((await boardItems(boardId)).map((i) => i.id))
  await cards.first().click()
  const pop = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Visualize', exact: true }) })
  await pop.getByRole('button', { name: 'Visualize', exact: true }).click()
  // a take is a staged item: it shows in the popover, not yet on the board
  await expect(page.getByRole('img', { name: / · take 1$/ })).toBeVisible({ timeout: 15_000 })
  await expectItemCount(page, 5)
  await page.getByRole('button', { name: 'Keep', exact: true }).click()
  await expectItemCount(page, 6)

  // the kept take is selected; find it by id and check its caption and verdict
  let generatedId = ''
  await expect
    .poll(async () => {
      generatedId = (await boardItems(boardId)).find((i) => !knownIds.has(i.id) && i.parent_item_id)?.id ?? ''
      return generatedId
    })
    .not.toBe('')
  const gen = (await boardItems(boardId)).find((i) => i.id === generatedId)!
  const label = gen.original_filename ?? gen.page_title ?? gen.page_url ?? gen.id
  await page.keyboard.press('Escape')
  await selectItem(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  await expect(page.getByRole('note', { name: 'Generated image' })).toHaveText(
    'generated · mock-image',
    { timeout: 10_000 },
  )
  await expect(page.locator('.credit-caption .verdict')).toBeVisible()
  await expect(page.locator('.credit-caption .verdict')).not.toHaveText('Checking…', { timeout: 15_000 })
})
