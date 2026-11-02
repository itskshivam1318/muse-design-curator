import { expect, test } from '@playwright/test'
import {
  apiJson,
  boardIdOf,
  boardItems,
  callout,
  canvas,
  closeLibrary,
  dropFiles,
  expectItemCount,
  flower,
  itemButton,
  openDimension,
  openLibrary,
  panToReach,
  renderUntilOk,
  selectItem,
  sitePath,
} from './helpers.ts'
import { SITE_URL } from './ports.ts'

/**
 * The demo on mock providers and the fixture corpus. Mock values are a deterministic hash of image,
 * prompt (which includes the board context) and schema, so a run sees the same values every time;
 * they are not meaningful. Exploring is the flower on a part's callout: Vary and its Maybe strip
 * are gone.
 */
test('demo flow: board, references, lens, link, video, explore, keep, not this, reload', async ({ page }) => {
  const context = 'A field watch for a 38 mm wrist: legible and plain, but warmer than steel.'
  let boardId = ''

  await test.step('1. create a board and type the context', async () => {
    await page.goto('/')
    await page.getByLabel('New board').fill('E2E field watch')
    await page.getByRole('button', { name: 'Create board' }).click()
    await expect(page).toHaveURL(/\/boards\/brd_/)
    boardId = boardIdOf(page)
    const bar = page.getByRole('region', { name: 'Board context' })
    await bar.getByRole('button', { name: /Say what it's for/ }).click()
    await bar.getByLabel('What is this board for?').fill(context)
    await bar.getByRole('button', { name: 'Save' }).click()
    await expect(bar.getByRole('button', { name: new RegExp(context.slice(0, 30)) })).toBeVisible()
  })

  const signals = page.getByRole('complementary', { name: 'Board signals' })

  await test.step('2. upload 3 images and drop 2 more; onboarding progress fills', async () => {
    await expect(page.getByRole('region', { name: 'Getting started' })).toBeVisible()
    await openLibrary(page)
    await page
      .getByLabel('Choose images or video to upload')
      .setInputFiles(['watch_01.jpg', 'watch_02.jpg', 'watch_03.jpg'].map(sitePath))
    await expectItemCount(page, 3)
    await expect(signals.getByRole('img', { name: '3 of 5 references added' })).toBeVisible()
    await dropFiles(page, canvas(page), ['watch_04.jpg', 'watch_05.jpg'].map(sitePath))
    await expectItemCount(page, 5)
    // five references unlock board intelligence: the progress row is replaced by the lens
    await expect(signals.getByText('Add 5 to unlock board intelligence')).toHaveCount(0)
  })

  await test.step('3. the lens is auto-chosen (watch); signals appear live', async () => {
    const bar = page.getByRole('region', { name: 'Board context' })
    // the board's items vote for the watch domain and the server attaches the curated lens itself:
    // no domain choice, no Save
    await expect(bar.getByText('· Watch', { exact: true })).toBeVisible()
    await expect(signals.getByText('Watch lens · curated')).toBeVisible()
    // parsing under the watch lens streams in; the profile groups appear without a reload
    await expect(signals.locator('.sig').first()).toBeVisible()
    await expect.poll(async () => (await boardItems(boardId)).every((i) => i.parse_status === 'completed')).toBe(true)
  })

  await test.step('4. paste a link to a page with og:image; it becomes an item', async () => {
    await openLibrary(page)
    await page.getByRole('button', { name: /Paste a link/ }).click()
    await page.getByLabel('Link to a page or image').fill(`${SITE_URL}/article.html`)
    await page.getByRole('button', { name: 'Add link' }).click()
    await expectItemCount(page, 6)
    await expect(itemButton(page, /^image Fixture article/)).toBeAttached()
  })

  await test.step('5. upload an MP4; frames appear; choose frame 2', async () => {
    await openLibrary(page)
    await page.getByLabel('Choose images or video to upload').setInputFiles(sitePath('clip.mp4'))
    await expectItemCount(page, 7)
    await closeLibrary(page) // it covers the strip and the board's left side
    await selectItem(page, /^video clip\.mp4/)
    await page.keyboard.press('f') // fit the board so the video is on screen
    // hover the video on the canvas (just under its toolbar) to reveal the frames strip
    const toolbar = page.getByRole('toolbar', { name: 'Item actions' })
    await expect(toolbar).toBeVisible()
    const strip = page.getByRole('group', { name: 'Video frames' })
    await expect(async () => {
      // re-hover each try: a single move can land before the canvas has settled after the fit
      const tb = (await toolbar.boundingBox())!
      await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height + 30)
      await expect(strip.getByRole('button')).toHaveCount(3, { timeout: 1_000 })
    }).toPass({ timeout: 15_000 })
    const frame2 = strip.getByRole('button', { name: 'Use frame at 2.0 s' }) // frames are 0-indexed: 0, 1, 2
    await frame2.click()
    await expect(frame2).toHaveAttribute('aria-pressed', 'true')
  })

  let sourceId = ''
  let optionId = ''

  await test.step('6. select an item; its callouts open a flower of note petals', async () => {
    await page.mouse.move(5, 5)
    await selectItem(page, /^image watch_01\.jpg/)
    sourceId = (await boardItems(boardId)).find((i) => i.original_filename === 'watch_01.jpg')!.id
    await expect(callout(page, 'Body')).toBeVisible()
    const f = await openDimension(page, 'Body colour')
    await expect(f.locator('img')).toHaveCount(0) // options are notes: nothing rendered yet
  })

  await test.step('7. render a petal inside its mask; keep it; it lands as an item linked to its source', async () => {
    const f = flower(page, 'Body colour')
    await panToReach(page, f)
    const card = await renderUntilOk(page, f, 'Generate image', 'Muse Image · inside the Body mask')
    optionId = (await f.locator('.petal.is-open').getAttribute('data-option-id'))!
    await card.getByRole('button', { name: 'Keep', exact: true }).click()
    await expectItemCount(page, 8)
    const kept = (await boardItems(boardId)).filter((i) => i.parent_item_id === sourceId && !i.staged)
    expect(kept).toHaveLength(1)
    await expect(f.locator(`[data-option-id="${optionId}"]`)).toHaveAttribute('aria-label', / · kept$/)
  })

  await test.step('8. drop another option as "Not this"; mark an item not-this', async () => {
    const f = flower(page, 'Body colour')
    const before = await f.getByTestId('petal').count()
    const other = f.locator('[data-testid="petal"]:not(.is-kept)').first()
    await other.click()
    await page.locator('.petal-card').getByRole('button', { name: 'Dismiss' }).click()
    await expect(f.getByTestId('petal')).toHaveCount(before - 1)
    await page.mouse.move(5, 5)
    await selectItem(page, /^image watch_05/)
    await page.keyboard.press('f') // the flower was panned into reach: fit the board back
    await page.getByRole('toolbar', { name: 'Item actions' }).getByRole('button', { name: 'Not this' }).click()
    await expect(itemButton(page, / · not this$/)).toHaveCount(1)
  })

  await test.step('9. reload; everything persists', async () => {
    const before = (await boardItems(boardId)).filter((i) => !i.staged)
    await page.reload()
    await expectItemCount(page, before.length)
    await openLibrary(page) // the Board signals panel lives in the Library, which is closed after a reload
    const bar = page.getByRole('region', { name: 'Board context' })
    await expect(bar.getByRole('button', { name: new RegExp(context.slice(0, 30)) })).toContainText('Watch')
    await expect(signals.getByText('Watch lens · curated')).toBeVisible()
    await expect(itemButton(page, / · not this$/)).toHaveCount(1)
    const after = await boardItems(boardId)
    const children = after.filter((i) => i.parent_item_id === sourceId && !i.staged)
    expect(children.map((i) => i.role)).toEqual(['reference']) // the kept result
    await expect(page.locator(`[data-testid="petal"][data-option-id="${optionId}"]`)).toHaveAttribute('aria-label', / · kept$/)
    // the chosen video frame survived the reload
    const video = after.find((i) => i.kind === 'video')!
    const { frames } = await apiJson<{ frames: { chosen: boolean; t_ms: number }[] }>(`/items/${video.id}/frames`)
    expect(frames.find((f) => f.chosen)?.t_ms).toBe(2000)
  })
})
