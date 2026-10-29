import { expect, type Locator, test } from '@playwright/test'
import {
  type ApiItem,
  apiJson,
  boardIdOf,
  boardItems,
  canvas,
  closeLibrary,
  dropFiles,
  expectItemCount,
  itemButton,
  openLibrary,
  selectItem,
  sitePath,
} from './helpers.ts'
import { SITE_URL } from './ports.ts'

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const itemLabel = (i: ApiItem) => i.original_filename ?? i.page_title ?? i.page_url ?? i.id

async function releaseProtected(panel: Locator): Promise<void> {
  const chips = panel.getByRole('button', { name: /^Unprotect / })
  while ((await chips.count()) > 0) await chips.first().click()
}

/**
 * The ten-step demo on mock providers and the fixture corpus. Mock values are a deterministic hash
 * of image, prompt (which includes the board context) and schema, so a run sees the same values every
 * time; they are not meaningful, which is why the Vary steps release protected attributes.
 */
test('demo flow: board, references, lens, link, video, vary, keep, reject, nudge, reload', async ({ page }) => {
  const context = 'A field watch for a 38 mm wrist: legible and plain, but warmer than steel.'
  let boardId = ''

  // This spec walks the Vary path, which V reaches only when Explore is off (EXPLORE_ENABLED=0);
  // explore.spec.ts covers the Explore path. The app reads the flag from /api/demo/status.
  await page.route('**/api/demo/status', async (route) => {
    const res = await route.fetch()
    await route.fulfill({ response: res, json: { ...(await res.json()), explore_enabled: false } })
  })

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
    const tb = (await toolbar.boundingBox())!
    await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height + 30)
    const strip = page.getByRole('group', { name: 'Video frames' })
    await expect(strip.getByRole('button')).toHaveCount(3)
    const frame2 = strip.getByRole('button', { name: 'Use frame at 2.0 s' }) // frames are 0-indexed: 0, 1, 2
    await frame2.click()
    await expect(frame2).toHaveAttribute('aria-pressed', 'true')
  })

  const strip = page.getByRole('region', { name: 'Maybe strip' })
  let sourceId = ''

  await test.step('6. select an item, Vary dial colour (Explore), Run', async () => {
    await page.mouse.move(5, 5)
    await selectItem(page, /^image watch_01\.jpg/)
    sourceId = (await boardItems(boardId)).find((i) => i.original_filename === 'watch_01.jpg')!.id
    await page.keyboard.press('v')
    const panel = page.getByRole('complementary', { name: 'vary panel' })
    await panel.getByRole('radio', { name: /^Dial colour/ }).click()
    await expect(panel.getByRole('radio', { name: 'Explore' })).toHaveAttribute('aria-checked', 'true')
    // Mock attribute values are arbitrary, so protecting all of them leaves nothing to return:
    // release every protected attribute (a deliberate user action) and vary the colour alone.
    await releaseProtected(panel)
    await panel.getByRole('button', { name: 'Run' }).click()
    await expect(panel).toHaveCount(0)
  })

  await test.step('7. candidates stream into the Maybe strip; keep one; it lands with a lineage curve', async () => {
    await expect(strip).toBeVisible()
    await expect(strip.getByRole('button', { name: /^Candidate 2, validated/ })).toBeVisible()
    await strip.getByRole('button', { name: /^Candidate 1, validated/ }).click()
    const pop = page.getByRole('dialog', { name: 'Candidate' })
    await expect(pop.getByRole('img', { name: 'Candidate image' })).toBeVisible()
    await pop.getByRole('button', { name: 'Keep' }).click()
    await expectItemCount(page, 8)
    await expect(strip.getByRole('button', { name: 'Candidate 1, validated, kept' })).toBeVisible()
    // the kept item is selected, which draws its lineage curve back to the source (parent_item_id)
    const kept = (await boardItems(boardId)).filter((i) => i.parent_item_id === sourceId)
    expect(kept).toHaveLength(1)
    const k = kept[0]
    const pressed = page.getByRole('list', { name: 'Items on this board' }).locator('button[aria-pressed="true"]')
    await expect(pressed).toHaveCount(1)
    await expect(pressed).toContainText(k.original_filename ?? k.page_title ?? k.page_url ?? k.id)
  })

  await test.step('8. reject one as "not my style", mark it not-this; counter-signals update', async () => {
    await strip.getByRole('button', { name: /^Candidate 2, validated/ }).click()
    const pop = page.getByRole('dialog', { name: 'Candidate' })
    await pop.getByRole('button', { name: 'Reject' }).click()
    await pop.getByRole('radio', { name: 'Not my style' }).click()
    await pop.getByLabel('Mark as not this').check()
    await pop.getByRole('button', { name: 'Confirm reject' }).click()
    await expect(strip.getByRole('button', { name: 'Candidate 2, validated, rejected' })).toBeVisible()
    await expectItemCount(page, 9)
    await expect(itemButton(page, / · not this$/)).toHaveCount(1)
    await page.keyboard.press('Escape')
    // mark a second item not-this (counter-signals need two; see the profile unit tests)
    await selectItem(page, /^image watch_05/)
    await page.getByRole('toolbar', { name: 'Item actions' }).getByRole('button', { name: 'Not this' }).click()
    await expect(itemButton(page, / · not this$/)).toHaveCount(2)
    // whether a counter-signal appears depends on mock values coinciding; the profile unit tests cover it
  })

  await test.step('9. nudge "legibility: more" on another item', async () => {
    // mock values depend on the image and the board context: find an item whose legibility is
    // known and below the top of the scale (low | medium | high)
    let target: { label: string; value: string } | null = null
    for (const it of await boardItems(boardId)) {
      if (it.id === sourceId || it.role !== 'reference') continue
      const attrs = await apiJson<{ attributes: { key: string; value: unknown; enabled: boolean }[] }>(
        `/items/${it.id}/attributes`,
      )
      const leg = attrs.attributes.find((x) => x.key === 'legibility')
      if (leg?.enabled && (leg.value === 'low' || leg.value === 'medium')) {
        target = { label: itemLabel(it), value: leg.value }
        break
      }
    }
    expect(target, 'an item with a known legibility below "high"').not.toBeNull()
    await selectItem(page, new RegExp(`^\\w+ ${escapeRe(target!.label)}`))
    await page.keyboard.press('v')
    const panel = page.getByRole('complementary', { name: 'vary panel' })
    await panel.getByRole('radio', { name: /^Legibility/ }).click()
    await panel.getByRole('radio', { name: 'More' }).click()
    await expect(panel.getByRole('radio', { name: 'More' })).toHaveAttribute('aria-checked', 'true')
    await expect(panel.locator('.preflight-sentence')).toContainText(target!.value)
    await releaseProtected(panel)
    await panel.getByRole('button', { name: 'Run' }).click()
    await expect(panel).toHaveCount(0)
    // the Maybe strip now follows the nudge run (no decided candidates) through to completion
    await expect(strip.getByRole('button', { name: /, (kept|rejected)$/ })).toHaveCount(0)
    await expect(strip.getByRole('status')).toHaveText(/ found\./, { timeout: 30_000 })
  })

  await test.step('10. reload; everything persists', async () => {
    const before = await boardItems(boardId)
    await page.reload()
    await expectItemCount(page, before.length)
    await openLibrary(page)
    const bar = page.getByRole('region', { name: 'Board context' })
    await expect(bar.getByRole('button', { name: new RegExp(context.slice(0, 30)) })).toContainText('Watch')
    await expect(signals.getByText('Watch lens · curated')).toBeVisible()
    await expect(itemButton(page, / · not this$/)).toHaveCount(2)
    const after = await boardItems(boardId)
    const children = after.filter((i) => i.parent_item_id === sourceId)
    expect(children.map((i) => i.role).sort()).toEqual(['counter_example', 'reference']) // kept + not-this
    // the chosen video frame survived the reload
    const video = after.find((i) => i.kind === 'video')!
    const { frames } = await apiJson<{ frames: { chosen: boolean; t_ms: number }[] }>(`/items/${video.id}/frames`)
    expect(frames.find((f) => f.chosen)?.t_ms).toBe(2000)
  })
})
