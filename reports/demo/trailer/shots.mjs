// Films the trailer's live UI shots in the real app with a visible mouse pointer.
// Writes reports/demo/trailer/shots/<name>.webm and <name>.marks.json (seconds since the shot began,
// for each moment the trailer cuts on).
//
//   node reports/demo/trailer/shots.mjs [--app http://localhost:5173] [--only name] [--live]
//
// The read-only shots (select and hover) always run. The LIVE shots click real actions (explore,
// render, keep, chat): they call the models, add items to the board and spend credit, so they run
// only with --live or --only <name>. Run them on an imported copy of the board
// (make board-export / board-import), not the original.
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { createRequire } from 'node:module'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(join(here, '../../../frontend/package.json'))
const { chromium } = require('@playwright/test')
const { values: args } = parseArgs({
  options: {
    app: { type: 'string', default: 'http://localhost:5173' },
    only: { type: 'string' },
    live: { type: 'boolean', default: false },
    car: { type: 'string', default: 'brd_01m6h989kz0tz8xjvjbp6zbz9x' }, // pass the copy's id
    room: { type: 'string', default: 'brd_01m6j4rrnz1zzx6qax1rya3j27' },
  },
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
    // a yellow ripple on every click, so a viewer sees what was pressed
    addEventListener('mousedown', (e) => {
      const r = document.createElement('div')
      Object.assign(r.style, { position: 'fixed', left: e.clientX - 22 + 'px', top: e.clientY - 22 + 'px', width: '44px', height: '44px',
        borderRadius: '50%', border: '4px solid #ffd640', zIndex: 2147483646, pointerEvents: 'none', transition: 'transform .45s ease-out, opacity .45s ease-out' })
      document.body.appendChild(r)
      requestAnimationFrame(() => { r.style.transform = 'scale(1.9)'; r.style.opacity = '0' })
      setTimeout(() => r.remove(), 500)
    }, true)
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

// moments to cut on, per shot: mark('render') stores seconds since the shot began
let t0 = 0
let marks = {}
const mark = (name) => { marks[name] = +((Date.now() - t0) / 1000).toFixed(2) }

// type like a person, not a paste
async function typeSlowly(page, locator, text) {
  await locator.click()
  for (const ch of text) {
    await page.keyboard.type(ch)
    await page.waitForTimeout(45 + Math.random() * 40)
  }
}

async function clickGlide(page, locator) {
  // the board can't scroll and its cards drift a little with the physics, so no scroll-into-view
  // or stability wait: glide to where it is and press there
  await locator.waitFor({ state: 'visible', timeout: 30000 })
  await glide(page, locator, 25)
  await page.waitForTimeout(350)
  const b = await locator.boundingBox()
  await page.mouse.click(b.x + b.width / 2, b.y + Math.min(b.height / 2, 24))
}


// the screen box of an element (or the union of several), logged with the time, for the camera
let boxes = []
async function box(page, name, target) {
  const r = await page.evaluate((sel) => {
    const els = typeof sel === 'string' ? [...document.querySelectorAll(sel)] : []
    const rs = els.map((e) => e.getBoundingClientRect()).filter((b) => b.width > 0 && b.height > 0)
    if (!rs.length) return null
    const x = Math.min(...rs.map((b) => b.left)), y = Math.min(...rs.map((b) => b.top))
    const X = Math.max(...rs.map((b) => b.right)), Y = Math.max(...rs.map((b) => b.bottom))
    return [x, y, X - x, Y - y]
  }, typeof target === 'string' ? target : null)
  let b = r
  if (!b && target && typeof target !== 'string') {
    const bb = await target.boundingBox()
    if (bb) b = [bb.x, bb.y, bb.width, bb.height]
  }
  if (b) boxes.push({ name, t: +((Date.now() - t0) / 1000).toFixed(2), box: b.map((v) => Math.round(v)) })
}
const cardOf = (page, title) =>
  page.locator('.callout-title', { hasText: title }).first().locator('xpath=ancestor::*[.//*[contains(@class,"callout-head")]][1]')

// a real camera move on the board: smooth ctrl+wheel steps anchored at (x, y), in (k < 0) or out (k > 0)
async function smoothZoom(page, x, y, steps, delta = -30) {
  await page.mouse.move(x, y, { steps: 18 })
  await page.keyboard.down('Control')
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, delta)
    await page.waitForTimeout(110)
  }
  await page.keyboard.up('Control')
  await page.waitForTimeout(400)
}

const LIVE_API = 'http://localhost:8100'
async function agentKept(sentAt) {
  // done when the board's newest run (a chat may continue an open one) keeps a take after we sent
  const r = await (await fetch(`${LIVE_API}/api/boards/${args.car}/agent-runs`)).json()
  const run = (r.runs ?? r)[0]
  if (!run) return false
  const d = await (await fetch(`${LIVE_API}/api/agent-runs/${run.id}`)).json()
  return d.steps.some((s) => s.tool === 'keep_option' && s.ok && Date.parse(s.created_at) > sentAt)
}

async function keptSince(sentAt) {
  const r = await (await fetch(`${LIVE_API}/api/boards/${args.car}/agent-runs`)).json()
  const run = (r.runs ?? r)[0]
  if (!run) return 0
  const d = await (await fetch(`${LIVE_API}/api/agent-runs/${run.id}`)).json()
  return d.steps.filter((s) => s.tool === 'keep_option' && s.ok && Date.parse(s.created_at) > sentAt).length
}

const LIVE = new Set(['car-explore', 'car-chat', 'story', 'story-dims', 'story-settings'])
const HIRES = new Set() // Chrome's headless screencast films at CSS size too, so no HIRES shot for now

const SHOTS = {
  // LIVE: more dimensions, one at a time, on the same coupe (real board zoom in and out)
  'story-dims': async (page) => {
    await page.goto(`${args.app}/boards/${args.car}`)
    await page.waitForTimeout(4000)
    mark('board')
    await page.mouse.move(1500, 900)
    await pick(page, 'note.png', 0)
    const st = await page.locator('.board-stage').boundingBox()
    const cx = st.x + st.width / 2, cy = st.y + st.height / 2
    await page.waitForTimeout(1000)
    mark('zoom-in')
    await smoothZoom(page, cx, cy, 4)
    await page.waitForTimeout(1500)
    mark('callouts')
    // shape attributes (lamp form, intake form) can't be explored, so two text dimensions
    for (const [key, re, flowerRe] of [['setting', /studio background/i, /background.*flower/i], ['trim', /trim extent/i, /trim.*flower/i]]) {
      const dim = page.locator('.callout-dim', { hasText: re }).first()
      if (!(await dim.count())) continue
      await box(page, `${key}-dim`, dim)
      await clickGlide(page, dim)
      mark(`${key}-explore`)
      const fresh = page.getByRole('group', { name: flowerRe }).locator('[data-testid="petal"].is-note')
      await fresh.first().waitFor({ timeout: 120000 })
      // the boldest option shows the move best: a wild one if there is one
      const wild = fresh.filter({ has: page.locator('.petal-tag[data-distance="wild"]') })
      const petal = (await wild.count()) ? wild.first() : fresh.first()
      await box(page, `${key}-petal`, petal)
      await page.waitForTimeout(1200)
      mark(`${key}-petals`)
      await clickGlide(page, petal)
      await page.waitForTimeout(1200)
      await box(page, `${key}-card`, '.petal-card')
      mark(`${key}-card`)
      await clickGlide(page, page.locator('.petal-render, .petal-primary').first())
      mark(`${key}-render`)
      await page.locator('.petal-check').first().waitFor({ timeout: 240000 })
      await box(page, `${key}-checked`, '.petal-card')
      mark(`${key}-checked`)
      await page.waitForTimeout(2200)
      const keep = page.locator('button.petal-primary', { hasText: 'Keep' }).first()
      if (await keep.count()) { await clickGlide(page, keep); mark(`${key}-kept`); await page.waitForTimeout(2000) }
    }
    mark('zoom-out')
    await smoothZoom(page, cx, cy, 4, 30)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(2500)
    mark('end')
  },
  // LIVE: the coupe in real places, asked of Muse in the chat
  'story-settings': async (page) => {
    await page.goto(`${args.app}/boards/${args.car}`)
    await page.waitForTimeout(4000)
    mark('board')
    const ask = page.getByPlaceholder('Ask Muse about this board')
    await glide(page, ask)
    await box(page, 'chat', '.agent-card')
    mark('ask')
    await typeSlowly(page, ask, 'Show the coupe in three real places: a coastal road at dusk, a rainy city street at night, and a mountain pass at sunrise. Keep the car exactly as it is.')
    await page.waitForTimeout(400)
    await page.keyboard.press('Enter')
    mark('sent')
    const sentAt = Date.now()
    const q = page.locator('.question-card:not(.is-answered)').first()
    const until = Date.now() + 8 * 60000
    let answered = false
    while (Date.now() < until) {
      if (!answered && (await q.count())) {
        await page.waitForTimeout(800)
        await box(page, 'question', q)
        mark('question')
        await page.waitForTimeout(2200)
        await clickGlide(page, q.locator('.question-choice').first())
        mark('answered')
        answered = true
      }
      if ((await keptSince(sentAt)) >= 3) { mark('landed'); break }
      await page.waitForTimeout(2000)
    }
    await box(page, 'chat-done', '.agent-card')
    await page.waitForTimeout(3000)
    mark('end')
  },
  // LIVE, 2x resolution, one take: the board, the coupe's parts, explore paint, then ask Muse.
  // Writes boxes into marks (marks.boxes) so the trailer's camera can zoom to each action.
  story: async (page) => {
    await page.goto(`${args.app}/boards/${args.car}`)
    await page.waitForTimeout(4000)
    mark('board')
    await page.mouse.move(1500, 900)
    await pick(page, 'note.png', 0) // selected and centred, still at the wide view
    const st = await page.locator('.board-stage').boundingBox()
    const cx = st.x + st.width / 2, cy = st.y + st.height / 2
    await page.waitForTimeout(1200)
    mark('zoom-in')
    await smoothZoom(page, cx, cy, 4) // glide in on the coupe (about 3.3x)
    await page.waitForTimeout(1800)
    mark('callouts')
    await box(page, 'callouts', '.callout-head')
    for (const part of ['Wheels', 'Headlamps']) {
      const card = cardOf(page, part)
      if (!(await card.count())) continue
      await glide(page, page.locator('.callout-title', { hasText: part }).first())
      await box(page, `part-${part.toLowerCase()}`, card)
      mark(`part-${part.toLowerCase()}`)
      await page.waitForTimeout(2400)
    }
    const dim = page.locator('.callout-dim', { hasText: /wheel design/i }).first()
    await box(page, 'explore-dim', dim)
    await clickGlide(page, dim)
    mark('explore')
    const flower = page.getByRole('group', { name: /wheel.*flower/i })
    const petal = flower.locator('[data-testid="petal"].is-note').first()
    await petal.waitFor({ timeout: 120000 })
    await page.waitForTimeout(1500)
    await box(page, 'flower', '[role=group][aria-label*="heel"] [data-testid="petal"]')
    await box(page, 'petal', petal)
    mark('petals')
    await clickGlide(page, petal)
    await page.waitForTimeout(1200)
    await box(page, 'card', '.petal-card')
    mark('card')
    await clickGlide(page, page.locator('.petal-render, .petal-primary').first())
    mark('render')
    await page.locator('.petal-check').first().waitFor({ timeout: 240000 })
    await box(page, 'card-checked', '.petal-card')
    mark('checked')
    await page.waitForTimeout(2500)
    const keep = page.locator('button.petal-primary', { hasText: 'Keep' }).first()
    if (await keep.count()) {
      await clickGlide(page, keep)
      mark('kept')
      await page.waitForTimeout(2500)
    }
    await page.waitForTimeout(800)
    mark('zoom-out')
    await smoothZoom(page, cx, cy, 4, 30) // glide back out: the kept take is on the board
    await page.keyboard.press('Escape')
    await page.waitForTimeout(2000)
    mark('board-again')
    // ask Muse
    const ask = page.getByPlaceholder('Ask Muse about this board')
    await glide(page, ask)
    await box(page, 'chat', '.agent-card')
    mark('ask')
    await typeSlowly(page, ask, 'Give me a darker colourway. Keep everything else exactly as it is.')
    await page.waitForTimeout(400)
    await page.keyboard.press('Enter')
    mark('sent')
    const sentAt = Date.now()
    const q = page.locator('.question-card:not(.is-answered)').first()
    const until = Date.now() + 6 * 60000
    let answered = false
    while (Date.now() < until) {
      if (!answered && (await q.count())) {
        await page.waitForTimeout(800)
        await box(page, 'question', q)
        mark('question')
        await page.waitForTimeout(2200)
        await clickGlide(page, q.locator('.question-choice').first())
        mark('answered')
        answered = true
      }
      if (await agentKept(sentAt)) { await box(page, 'chat-done', '.agent-card'); mark('landed'); break }
      await page.waitForTimeout(1500)
    }
    await page.waitForTimeout(3000)
    mark('end')
  },
  // LIVE. The core loop on one picture: dimension -> flower of options -> render one -> check -> keep.
  'car-explore': async (page) => {
    await page.goto(`${args.app}/boards/${args.car}`)
    await page.waitForTimeout(3500)
    await page.mouse.move(1500, 900)
    await pick(page, 'note.png', 4)
    await page.waitForTimeout(2500)
    mark('callouts')
    const dim = page.locator('.callout-dim', { hasText: /paint|colour|color/i }).first()
    await clickGlide(page, dim)
    mark('explore')
    // the options arrive as petals around the hub
    // a petal of the paint flower that has no take yet (is-note), so pressing it shows Render
    const petal = page.getByRole('group', { name: /paint.*flower/i }).locator('[data-testid="petal"].is-note').first()
    await petal.waitFor({ timeout: 120000 })
    await page.waitForTimeout(1500)
    mark('petals')
    await clickGlide(page, petal)
    await page.waitForTimeout(1200)
    mark('card')
    const render = page.locator('.petal-render, .petal-primary').first()
    await clickGlide(page, render)
    mark('render')
    await page.locator('.petal-check').first().waitFor({ timeout: 240000 })
    mark('checked')
    await page.waitForTimeout(3000) // hold on the check line
    const keep = page.locator('button.petal-primary', { hasText: 'Keep' }).first()
    if (await keep.count()) {
      await clickGlide(page, keep)
      mark('kept')
      await page.waitForTimeout(3000)
    }
  },
  // LIVE. Ask the in-app agent; film its steps landing on the board and answer its question.
  'car-chat': async (page) => {
    await page.goto(`${args.app}/boards/${args.car}`)
    await page.waitForTimeout(3500)
    await page.mouse.move(1500, 900)
    const ask = page.getByPlaceholder('Ask Muse about this board')
    await glide(page, ask)
    mark('ask')
    await typeSlowly(page, ask, 'Give me a darker colourway. Keep everything else exactly as it is.')
    await page.waitForTimeout(500)
    await page.keyboard.press('Enter')
    mark('sent')
    // film the agent working; answer its first question if it asks one
    const q = page.locator('.question-card:not(.is-answered)').first()
    const done = Date.now() + 8 * 60000
    while (Date.now() < done) {
      if (await q.count()) {
        mark('question')
        await page.waitForTimeout(2500)
        const choice = q.locator('.question-choice').first()
        await clickGlide(page, choice)
        mark('answered')
      }
      if (await page.locator('.petal-check').count()) { mark('checked'); break }
      await page.waitForTimeout(1000)
    }
    await page.waitForTimeout(4000)
  },
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
  if (LIVE.has(name) && !args.live && args.only !== name) continue
  // A HIRES shot is captured at 2x pixel density through Chrome's screencast (each frame saved with
  // its time), because Playwright's recorder always films at the viewport's CSS size.
  const hi = HIRES.has(name)
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: hi ? 2 : 1,
    ...(hi ? {} : { recordVideo: { dir: out, size: { width: 1920, height: 1080 } } }),
  })
  await ctx.addInitScript(CURSOR)
  const page = await ctx.newPage()
  const frames = []
  let cdp = null
  const fdir = join(out, `${name}.frames`)
  if (hi) {
    mkdirSync(fdir, { recursive: true })
    cdp = await ctx.newCDPSession(page)
    cdp.on('Page.screencastFrame', async ({ data, sessionId }) => {
      const t = (Date.now() - t0) / 1000
      const f = `${String(frames.length).padStart(6, '0')}.jpg`
      writeFileSync(join(fdir, f), Buffer.from(data, 'base64'))
      frames.push([f, t])
      await cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {})
    })
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: 3840, maxHeight: 2160, everyNthFrame: 1 })
  }
  t0 = Date.now()
  marks = {}
  boxes = []
  try {
    await shot(page)
  } catch (err) {
    console.error(`${name}: ${err.message}`)
  }
  await page.waitForTimeout(800)
  if (hi) {
    await cdp.send('Page.stopScreencast').catch(() => {})
    // a concat list: each frame held until the next one arrived
    const lines = frames.map(([f, t], k) => `file '${f}'\nduration ${((frames[k + 1]?.[1] ?? t + 0.5) - t).toFixed(3)}`)
    writeFileSync(join(fdir, 'frames.txt'), lines.join('\n') + `\nfile '${frames.at(-1)[0]}'\n`)
    writeFileSync(join(fdir, 'start.json'), JSON.stringify({ first_frame_t: frames[0]?.[1] ?? 0 }))
    await ctx.close()
  } else {
    const video = page.video()
    await ctx.close()
    renameSync(await video.path(), join(out, `${name}.webm`))
  }
  writeFileSync(join(out, `${name}.marks.json`), JSON.stringify(boxes.length ? { ...marks, boxes } : marks, null, 1))
  console.log(`${name} done`)
}
await browser.close()
