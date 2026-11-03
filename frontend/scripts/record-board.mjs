// Films a Muse board while an agent works it, then saves the run and its steps.
//
//   node frontend/scripts/record-board.mjs --board <id> --slug <car|ui|room|outerwear>
//        [--app http://localhost:5173] [--api http://localhost:8000] [--max-min 60]
//
// Writes reports/demo/<slug>/: a .webm (Chromium, 1920x1080), run.json (the run with its steps) and
// steps.md (one line per step with its time since the recording began, so a snippet can be found in
// the video). Follows the board's newest run that started, or took a step, after recording began
// (a run the agent joined counts) and stops 5 s after it reached done, needs_input or paused with no
// newer such run; or at --max-min. Refuses (exit 2) if reports/demo/<slug>/ already holds a video or
// run.json: use another slug (e.g. outerwear-2). Exits 1 if the board does not load.
import { existsSync, mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { chromium } from '@playwright/test'

const POLL_MS = 5000
const HOLD_MS = 5000
const STOPPED = new Set(['done', 'needs_input', 'paused'])
const OPEN = new Set(['running', 'needs_input'])

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
for (const name of [`${args.slug}.webm`, 'run.json']) {
  if (existsSync(join(outDir, name))) {
    console.error(`${join(outDir, name)} already exists; a new recording would overwrite it. Use another --slug (e.g. ${args.slug}-2) or move the files first.`)
    process.exit(2)
  }
}
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
    // A run counts if it was created after recording began, or the agent joined one that was
    // already open and has since taken a step (run.updated_at is not bumped by steps, so look).
    const mine = []
    for (const r of runs) {
      let counts = Date.parse(r.created_at) >= t0
      if (!counts && (OPEN.has(r.status) || Date.parse(r.updated_at) >= t0)) {
        const full = await api(`/agent-runs/${r.id}`)
        counts = full.steps.some((s) => Date.parse(s.created_at) >= t0)
      }
      if (counts) mine.push(r)
    }
    // Follow the newest such run: a paused run does not end the recording while a newer one exists.
    const run = mine.reduce((a, b) => (!a || Date.parse(b.created_at) > Date.parse(a.created_at) ? b : a), null)
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
      'Time is mm:ss since the recording began (the video starts at 00:00). A step\'s time is when its call returned: a long render_view shows the time its picture appeared, not when it started.',
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
