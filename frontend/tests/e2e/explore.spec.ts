import { expect, test } from '@playwright/test'
import { boardIdOf, boardItems, expectItemCount, selectItem, sitePath } from './helpers.ts'

/**
 * Explore -> Visualize on mock providers: the mock reasoning provider returns eight options named
 * like "Option A 3f2c"; the mock image provider's model id is "mock-image".
 */
test('explore option then visualize', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('New board').fill('E2E explore')
  await page.getByRole('button', { name: 'Create board' }).click()
  await expect(page).toHaveURL(/\/boards\/brd_/)
  const boardId = boardIdOf(page)
  const bar = page.getByRole('region', { name: 'Board context' })
  await bar.getByRole('button', { name: /Say what it's for/ }).click()
  await bar.getByLabel('What is this board for?').fill('A field watch for a 38 mm wrist.')
  await bar.getByRole('button', { name: 'Save' }).click()

  await page
    .getByLabel('Choose images or video to upload')
    .setInputFiles(['watch_01.jpg', 'watch_02.jpg', 'watch_03.jpg', 'watch_04.jpg', 'watch_05.jpg'].map(sitePath))
  await expectItemCount(page, 5)
  await expect(page.getByRole('complementary', { name: 'Board signals' }).getByText('Watch lens · curated')).toBeVisible()
  await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)

  await selectItem(page, /^image watch_01\.jpg/)
  await page.keyboard.press('v')
  const panel = page.getByRole('complementary', { name: 'explore panel' })
  await expect(panel).toBeVisible()

  // the first explorable attribute (shapes are not offered)
  await panel.locator('.explore-attrs .target').first().click()
  await panel.getByRole('button', { name: 'Explore', exact: true }).click()

  const rows = panel.locator('.explore-option')
  await expect(rows.first()).toBeVisible({ timeout: 30_000 })
  const n = await rows.count()
  expect(n).toBeGreaterThanOrEqual(6)
  await expect(page.getByTestId('option-note')).toHaveCount(n)

  await rows.first().getByRole('button', { name: /^Visualize / }).click()
  const before = (await boardItems(boardId)).length
  await expect.poll(async () => (await boardItems(boardId)).length, { timeout: 10_000 }).toBe(before + 1)
  await expectItemCount(page, 6)

  // select the generated item (the newest) and read the caption and verdict
  const items = await boardItems(boardId)
  const gen = items[items.length - 1]
  await page.keyboard.press('Escape')
  await selectItem(page, new RegExp(`${gen.original_filename ?? gen.page_title ?? gen.id}`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  await expect(page.getByRole('note', { name: 'Generated image' })).toHaveText(
    'generated · mock-image',
    { timeout: 10_000 },
  )
  await expect(page.locator('.credit-caption .verdict')).toBeVisible()
  await expect(page.locator('.credit-caption .verdict')).not.toHaveText('Checking…', { timeout: 15_000 })
})
