// Films each recorded run's spotlight replay (Show me how) at 1920x1080, holding every card, and
// logs when each card appears so the rough cut can pick them out. Read-only: it only opens
// /boards/<id>?replay=<run> and presses Next.
//
//   node reports/demo/record_replays.mjs [--app http://localhost:5173] [--hold 4] [--only slug,slug]
//
// Writes reports/demo/replays/<slug>.webm and reports/demo/replays/<slug>.json
// ([{card, of, step, say, t}] with t in seconds since the video began).
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { createRequire } from 'node:module'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(join(here, '../../frontend/package.json'))
const { chromium } = require('@playwright/test')

const { values: args } = parseArgs({
  options: {
    app: { type: 'string', default: 'http://localhost:5173' },
    hold: { type: 'string', default: '4' },
    only: { type: 'string' },
  },
})
const HOLD_MS = Number(args.hold) * 1000
const RUNS = [
  ['car', 'brd_01m6h989kz0tz8xjvjbp6zbz9x', 'arun_01m6h991xyrzxq1xyvhrag2pqk'],
  ['ui', 'brd_01m6hcp4q8vrt11mnpw6jrmpb4', 'arun_01m6hcpsxzz7fx878hx8fhsn7n'],
  ['room', 'brd_01m6j4rrnz1zzx6qax1rya3j27', 'arun_01m6j4sg80tqra73g2y11dvnx9'],
  ['outerwear', 'brd_01m6j5n5eqdmxv33zhw03qesx5', 'arun_01m6j5npnz586e22mbk8vrxat4'],
  ['outerwear-2', 'brd_01m6j5n5eqdmxv33zhw03qesx5', 'arun_01m6j84dj1qq9h5pznksgzmwha'],
  ['ui-premium', 'brd_01m6hcp4q8vrt11mnpw6jrmpb4', 'arun_01m6jqd3132yctrry60vehkftr'],
  ['car-put', 'brd_01m6h989kz0tz8xjvjbp6zbz9x', 'arun_01m6jqa2kbp7784pvd1pj9fm6r'],
]
const out = join(here, 'replays')
mkdirSync(out, { recursive: true })

const browser = await chromium.launch()
for (const [slug, board, run] of RUNS) {
  if (args.only && !args.only.split(',').includes(slug)) continue
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: out, size: { width: 1920, height: 1080 } },
  })
  const page = await ctx.newPage()
  const t0 = Date.now()
  await page.goto(`${args.app}/boards/${board}?replay=${run}`)
  const dialog = page.getByRole('dialog', { name: 'Replay' })
  await dialog.waitFor({ timeout: 30_000 })
  const cards = []
  for (;;) {
    await page.waitForTimeout(700) // the pan settles
    const text = await dialog.innerText()
    const [, n, m] = /(\d+) of (\d+)/.exec(text) ?? []
    const step = /Step (\d+)/.exec(text)?.[1]
    const say = text.split('\n').filter((l) => l && !/^Step \d+$|^\d+ of \d+$|^(Back|Next|Done|×)$/.test(l)).join(' ')
    cards.push({ card: Number(n), of: Number(m), step: Number(step), say, t: (Date.now() - t0) / 1000 })
    await page.waitForTimeout(HOLD_MS)
    const done = await page.getByRole('button', { name: 'Done' }).count()
    if (done) {
      await page.getByRole('button', { name: 'Done' }).click()
      break
    }
    await page.keyboard.press('ArrowRight')
  }
  await page.waitForTimeout(1500)
  const video = page.video()
  await ctx.close()
  renameSync(await video.path(), join(out, `${slug}.webm`))
  writeFileSync(join(out, `${slug}.json`), JSON.stringify(cards, null, 1))
  console.log(`${slug}: ${cards.length} cards`)
}
await browser.close()
