// Films a Muse board while an agent works it, then saves the run and its steps.
//
//   node frontend/scripts/record-board.mjs --board <id> --slug <car|ui|room|outerwear>
//        [--app http://localhost:5173] [--api http://localhost:8000] [--max-min 60]
//
// Writes reports/demo/<slug>/: a .webm (Chromium, 1920x1080), run.json (the run with its steps) and
// steps.md (one line per step with its time since the recording began, so a snippet can be found in
// the video). Stops 5 s after the board has a run that started after recording began and reached
// done, needs_input or paused; or at --max-min. Exits non-zero if the board does not load.
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { chromium } from '@playwright/test'

const POLL_MS = 5000
const HOLD_MS = 5000
const STOPPED = new Set(['done', 'needs_input', 'paused'])

const { values: args } = parseArgs({
  options: {
    board: { type: 'string' },
    slug: { type: 'string' },
    app: { type: 'string', default: 'http://localhost:5173' },
    api: { type: 'string', default: 'http://localhost:8000' },
    'max-min': { type: 'string', default: '60' },
  },
})
if (!args.board || !args.slug || !/^[a-z0-9-]+$/.test(args.slug)) {
  console.error('usage: record-board.mjs --board <id> --slug <name> [--app URL] [--api URL] [--max-min N]')
  process.exit(2)
}
const maxMs = Number(args['max-min']) * 60_000
if (!(maxMs > 0)) {
  console.error('--max-min must be a positive number')
  process.exit(2)
}
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const outDir = join(root, 'reports', 'demo', args.slug)
mkdirSync(outDir, { recursive: true })

const boardId = encodeURIComponent(args.board)
const api = async (path) => {
  const r = await fetch(`${args.api}/api${path}`)
  if (!r.ok) throw new Error(`${path} answered ${r.status}`)
  return r.json()
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const mmss = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } },
})
const page = await context.newPage()
// The video's t=0 is the page's creation; take our clock right here so step times line up with it.
const t0 = Date.now()

try {
  const res = await page.goto(`${args.app}/boards/${boardId}`, { waitUntil: 'domcontentloaded' })
  if (!res || !res.ok()) throw new Error(`board page answered ${res?.status()}`)
  await api(`/boards/${boardId}`) // 404 here means the board id is wrong
  await page.waitForSelector('canvas', { timeout: 30_000 })
  console.log(`recording board ${args.board} into ${outDir}`)

  let runId = null
  let finished = false
  while (Date.now() - t0 < maxMs) {
    await sleep(POLL_MS)
    const { runs } = await api(`/boards/${boardId}/agent-runs`)
    const mine = runs.filter((r) => Date.parse(r.created_at) >= t0)
    const run = mine.find((r) => r.id === runId) ?? mine[0]
    if (!run) continue
    runId = run.id
    if (STOPPED.has(run.status)) {
      console.log(`run ${run.id} is ${run.status}; holding ${HOLD_MS / 1000}s`)
      await sleep(HOLD_MS)
      finished = true
      break
    }
  }
  if (!finished) console.warn(`stopped at --max-min; ${runId ? `run ${runId} still going` : 'no run started'}`)
  if (runId) {
    const full = await api(`/agent-runs/${runId}`)
    writeFileSync(join(outDir, 'run.json'), JSON.stringify(full, null, 2) + '\n')
    const lines = [
      `# ${args.slug}: run ${full.id} (${full.status})`,
      '',
      `Goal: ${full.goal ?? ''}`,
      '',
      'Time is mm:ss since the recording began (the video starts at 00:00).',
      '',
    ]
    full.steps.forEach((s, i) => {
      const at = mmss(Date.parse(s.created_at) - t0)
      const star = s.highlight ? ' ★' : ''
      lines.push(`${i + 1}. ${at} \`${s.tool}\` ${s.ok ? 'ok' : 'refused'}${star} ${s.say ?? ''}`.trimEnd())
    })
    writeFileSync(join(outDir, 'steps.md'), lines.join('\n') + '\n')
    console.log(`saved run.json and steps.md (${full.steps.length} steps)`)
  }
} catch (err) {
  console.error(`board did not load or the run could not be read: ${err.message}`)
  process.exitCode = 1
} finally {
  const video = page.video()
  await context.close() // flushes the video
  await browser.close()
  if (video) {
    const dest = join(outDir, `${args.slug}.webm`)
    renameSync(await video.path(), dest)
    console.log(`video: ${dest}`)
  }
}
