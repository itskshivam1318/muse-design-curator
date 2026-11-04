// Films the trailer's live UI shots in the real app (read-only: it selects and hovers, nothing more),
// with a visible mouse pointer. Writes reports/demo/trailer/shots/<name>.webm.
//
//   node reports/demo/trailer/shots.mjs [--app http://localhost:5173] [--only name]
import { mkdirSync, renameSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { createRequire } from 'node:module'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(join(here, '../../../frontend/package.json'))
const { chromium } = require('@playwright/test')
const { values: args } = parseArgs({
  options: { app: { type: 'string', default: 'http://localhost:5173' }, only: { type: 'string' } },
})
const out = join(here, 'shots')
mkdirSync(out, { recursive: true })

// a pointer that follows the mouse (headless Chromium draws none)
const CURSOR = `
  addEventListener('DOMContentLoaded', () => {
    const c = document.createElement('div')
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M4 2l18 12-8 1.5L18 25l-3.5 1.6-4-9.4L4 22z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
    Object.assign(c.style, { position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none', transform: 'translate(-200px,-200px)' })
    document.body.appendChild(c)
    addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + (e.clientX - 4) + 'px,' + (e.clientY - 2) + 'px)' }, true)
  })`

async function glide(page, locator, steps = 30) {
  const b = await locator.boundingBox()
  if (!b) throw new Error('not on screen')
  await page.mouse.move(b.x + b.width / 2, b.y + Math.min(b.height / 2, 24), { steps })
}

async function pick(page, label, notches) {
  await page.locator('.left-rail [data-rail="library"]').click()
  await page.locator('.lib-row', { hasText: new RegExp(`^${label.replace('.', '\\.')}$`) }).first().click()
  await page.keyboard.press('Escape') // closes the rail; the picture stays selected and centred
  await page.waitForTimeout(600)
  // zoom in on it: ctrl+wheel at the stage centre, where the pick centred it
  const b = await page.locator('.board-stage').boundingBox()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 20 })
  await page.keyboard.down('Control')
  for (let i = 0; i < notches; i++) {
    await page.mouse.wheel(0, -100)
    await page.waitForTimeout(90)
  }
  await page.keyboard.up('Control')
}

const SHOTS = {
  // physical dimensions: the coupe's parts light up one by one
  'car-physical': async (page) => {
    await page.goto(`${args.app}/boards/brd_01m6h989kz0tz8xjvjbp6zbz9x`)
    await page.waitForTimeout(3500)
    await page.mouse.move(1500, 900)
    await pick(page, 'note.png', 4)
    await page.waitForTimeout(3000)
    for (const part of ['Wheels', 'Headlamps', 'Front panel', 'Paint']) {
      const card = page.locator('.callout-title', { hasText: part }).first()
      if (!(await card.count())) continue
      await glide(page, card)
      await page.waitForTimeout(2600)
    }
  },
  // abstract dimensions: the room's whole-picture reading
  'room-abstract': async (page) => {
    await page.goto(`${args.app}/boards/brd_01m6j4rrnz1zzx6qax1rya3j27`)
    await page.waitForTimeout(3500)
    await page.mouse.move(1500, 900)
    await pick(page, 'note.png', 3)
    await page.waitForTimeout(3000)
    for (const part of ['Whole item']) {
      const card = page.locator('.callout-title', { hasText: part }).first()
      if (!(await card.count())) continue
      await glide(page, card)
      await page.waitForTimeout(3000)
    }
  },
}

const browser = await chromium.launch()
for (const [name, shot] of Object.entries(SHOTS)) {
  if (args.only && args.only !== name) continue
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: out, size: { width: 1920, height: 1080 } },
  })
  await ctx.addInitScript(CURSOR)
  const page = await ctx.newPage()
  try {
    await shot(page)
  } catch (err) {
    console.error(`${name}: ${err.message}`)
  }
  await page.waitForTimeout(800)
  const video = page.video()
  await ctx.close()
  renameSync(await video.path(), join(out, `${name}.webm`))
  console.log(`${name} done`)
}
await browser.close()
