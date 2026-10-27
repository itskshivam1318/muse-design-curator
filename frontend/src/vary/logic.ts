/** Pure helpers behind Inspect, Vary, the Maybe strip and Compare. No React, no network. */
import type {
  AttrKind,
  AttributeSpec,
  AttrValue,
  BoardProfile,
  CandidateState,
  ItemAttribute,
  LiveProgress,
  LiveSourceStatus,
  LiveSummary,
  RunSummary,
  VaryMode,
} from '../api'

export const RESULT_SIZE = 6

// ---- kinds & specs ----

export const canNudge = (kind: string): boolean => kind === 'ordinal' || kind === 'number'

export function modesFor(kind: string): VaryMode[] {
  return canNudge(kind) ? ['explore', 'prefer', 'avoid', 'nudge'] : ['explore', 'prefer', 'avoid']
}

export interface NumberBounds {
  unit: string
  min: number
  max: number
  tolerance: number
}

export function scaleOf(spec: AttributeSpec | undefined): string[] {
  return Array.isArray(spec?.scale) ? (spec.scale as string[]) : []
}

export function vocabularyOf(spec: AttributeSpec | undefined): string[] {
  return Array.isArray(spec?.vocabulary) ? (spec.vocabulary as string[]) : []
}

export function numberBounds(spec: AttributeSpec | undefined): NumberBounds | null {
  if (!spec || spec.kind !== 'number') return null
  const n = (v: unknown, d: number) => (typeof v === 'number' ? v : d)
  return { unit: String(spec.unit ?? ''), min: n(spec.min, 0), max: n(spec.max, 100), tolerance: n(spec.tolerance, 1) }
}

// ---- values ----

/** "royal_blue" → "royal blue", 40 → "40 mm", true → "yes"; null → "unknown". */
export function formatValue(value: AttrValue | undefined, unit?: string): string {
  if (value === null || value === undefined || value === '') return 'unknown'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') {
    const n = Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100)
    return unit ? `${n} ${unit}` : n
  }
  return String(value).replace(/_/g, ' ')
}

/** Named colours a colour attribute can take (mirrors backend measure/palette.COLOR_TABLE). */
export const COLOR_TABLE: Record<string, string> = {
  black: '#000000', white: '#ffffff', grey: '#808080', silver: '#c0c0c0', charcoal: '#36454f',
  navy: '#000080', blue: '#0000ff', royal_blue: '#4169e1', teal: '#008080', green: '#00a000',
  olive: '#808000', sage: '#9caf88', yellow: '#ffff00', mustard: '#e1ad01', orange: '#ff8c00',
  rust: '#b7410e', red: '#ff0000', burgundy: '#800020', pink: '#ff69b4', blush: '#de5d83',
  purple: '#800080', lavender: '#b57edc', brown: '#654321', tan: '#d2b48c', beige: '#f5f5dc',
  cream: '#fffdd0', champagne: '#f7e7ce', gold: '#d4af37', salmon: '#fa8072', khaki: '#c3b091',
}

/** A hex for a colour attribute: its measured hex, a hex value, or the named colour's hex. */
export function colorHex(value: AttrValue | undefined, measured?: Record<string, unknown> | null): string | null {
  const m = measured?.hex
  if (typeof m === 'string' && /^#[0-9a-f]{6}$/i.test(m)) return m
  if (typeof value !== 'string') return null
  if (/^#[0-9a-f]{6}$/i.test(value)) return value
  return COLOR_TABLE[value] ?? null
}

// ---- nudge ----

export type NudgeResult = { ok: true; value: string | number; index: number | null } | { ok: false }

/** Where a nudge lands: an ordinal step, or a number moved by 2 × tolerance per step. */
export function nudgeTarget(
  spec: AttributeSpec,
  current: AttrValue | undefined,
  direction: 'more' | 'less',
  steps: 1 | 2,
): NudgeResult {
  const sign = direction === 'more' ? 1 : -1
  if (spec.kind === 'ordinal') {
    const scale = scaleOf(spec)
    const at = typeof current === 'string' ? scale.indexOf(current) : -1
    if (at === -1) return { ok: false }
    const idx = at + sign * steps
    return idx >= 0 && idx < scale.length ? { ok: true, value: scale[idx], index: idx } : { ok: false }
  }
  const b = numberBounds(spec)
  if (!b || typeof current !== 'number') return { ok: false }
  const next = Math.round((current + sign * steps * 2 * b.tolerance) * 1000) / 1000
  return next >= b.min && next <= b.max ? { ok: true, value: next, index: null } : { ok: false }
}

// ---- preflight ----

export interface PreflightInput {
  targetLabel: string
  mode: VaryMode
  values?: string[]
  nudge?: { direction: 'more' | 'less'; steps: 1 | 2 } | null
  current?: AttrValue
  target?: AttrValue
  unit?: string
  protectedLabels: string[]
}

export function joinList(parts: string[], last = 'and'): string {
  if (parts.length <= 1) return parts.join('')
  return `${parts.slice(0, -1).join(', ')} ${last} ${parts[parts.length - 1]}`
}

/** One sentence the user reads before Run: what changes, how, and what stays. */
export function preflightSentence(p: PreflightInput): string {
  const vals = (p.values ?? []).map((v) => formatValue(v, p.unit))
  let head: string
  switch (p.mode) {
    case 'explore':
      head = `Explore ${p.targetLabel} away from ${formatValue(p.current, p.unit)}`
      break
    case 'prefer':
      head = `Prefer ${p.targetLabel} ${joinList(vals, 'or') || '…'}`
      break
    case 'avoid':
      head = `Avoid ${p.targetLabel} ${joinList(vals, 'or') || '…'}`
      break
    case 'nudge': {
      const n = p.nudge ?? { direction: 'more', steps: 1 }
      const change = `${formatValue(p.current, p.unit)} → ${formatValue(p.target, p.unit)}`
      head = `Nudge ${p.targetLabel} ${n.direction} by ${n.steps} ${n.steps === 1 ? 'step' : 'steps'} (${change})`
      break
    }
  }
  const tail = p.protectedLabels.length
    ? `keeping ${joinList(p.protectedLabels)} unchanged`
    : 'with nothing protected'
  return `${head}, ${tail}.`
}

// ---- protected & targets ----

export type ProtectReason = 'board_signal' | 'user_confirmed' | 'same_part' | 'suggested'

export interface ProtectedRow {
  key: string
  label: string
  value: AttrValue
  kind: AttrKind
  isBoardSignal: boolean
  strength: number
  /** Switched on by default (see `reason`). */
  preselected: boolean
  reason: ProtectReason
}

const SIGNAL_MIN_CONSISTENCY = 0.6
const SIGNAL_MIN_KNOWN = 3
const PRESELECT_MIN = 3

/**
 * Mirror of backend `propose_protected`: every enabled, known, non-target attribute as a chip.
 * Pre-selected: board signals (consistency >= 0.6, n_known >= 3), edited or confirmed values, and,
 * while that gives fewer than 3, the next same-part attributes in lens order. The shared fixture
 * `backend/tests/fixtures/protected_defaults.json` keeps both implementations in step.
 */
export function orderProtected(
  attrs: readonly ItemAttribute[],
  targetKey: string,
  profile: BoardProfile | null | undefined,
): ProtectedRow[] {
  const strength = new Map(
    (profile?.signals ?? [])
      .filter((s) => s.consistency >= SIGNAL_MIN_CONSISTENCY && s.n_known >= SIGNAL_MIN_KNOWN)
      .map((s) => [s.key, s.consistency]),
  )
  const part = attrs.find((a) => a.key === targetKey)?.part ?? null
  const rows = attrs
    .filter((a) => a.enabled && a.value !== null && a.key !== targetKey)
    .map((a) => {
      const reason: ProtectReason = strength.has(a.key)
        ? 'board_signal'
        : a.status === 'edited' || a.status === 'confirmed'
          ? 'user_confirmed'
          : 'suggested'
      return {
        row: {
          key: a.key,
          label: a.label,
          value: a.value,
          kind: a.kind,
          isBoardSignal: strength.has(a.key),
          strength: strength.get(a.key) ?? 0,
          preselected: reason !== 'suggested',
          reason,
        } as ProtectedRow,
        part: a.part,
      }
    })
  let chosen = rows.filter((r) => r.row.preselected).length
  if (part !== null) {
    for (const r of rows) {
      if (chosen >= PRESELECT_MIN) break
      if (!r.row.preselected && r.part === part) {
        r.row.preselected = true
        r.row.reason = 'same_part'
        chosen++
      }
    }
  }
  // Array.prototype.sort is stable, so ties keep lens order
  return rows
    .map((r) => r.row)
    .sort((a, b) => Number(b.isBoardSignal) - Number(a.isBoardSignal) || b.strength - a.strength)
}

/** The keys switched on by default. */
export const defaultSelection = (rows: readonly ProtectedRow[]): Set<string> =>
  new Set(rows.filter((r) => r.preselected).map((r) => r.key))

/** "Protect all": every proposed chip. */
export const protectAll = (rows: readonly ProtectedRow[]): Set<string> => new Set(rows.map((r) => r.key))

/** Target candidates: the board's tensions first (in tension order), then the lens order. */
export function sortTargets<T extends { key: string }>(lensAttrs: readonly T[], profile: BoardProfile | null | undefined): T[] {
  const tension = new Map((profile?.tensions ?? []).map((t, i) => [t.key, i]))
  return lensAttrs
    .map((a, i) => ({ a, i }))
    .sort((x, y) => {
      const tx = tension.get(x.a.key)
      const ty = tension.get(y.a.key)
      if (tx !== undefined && ty !== undefined) return tx - ty
      if (tx !== undefined) return -1
      if (ty !== undefined) return 1
      return x.i - y.i
    })
    .map(({ a }) => a)
}

export const isTension = (key: string, profile: BoardProfile | null | undefined) =>
  (profile?.tensions ?? []).some((t) => t.key === key)
export const isBoardSignal = (key: string, profile: BoardProfile | null | undefined) =>
  (profile?.signals ?? []).some((s) => s.key === key)

// ---- strip ----

export type BarState = 'validated' | 'uncertain'

/** Candidate state → the 3 px bar under its thumbnail (blue validated, amber uncertain). */
export function barState(state: CandidateState): BarState | null {
  return state === 'validated' || state === 'uncertain' ? state : null
}

export interface ShortfallText {
  /** "Why only 3?" when fewer than six came back, else null. */
  link: string | null
  headline: string
  lines: string[]
  mostCommon: string | null
}

export function shortfallText(summary: RunSummary | null | undefined, size = RESULT_SIZE): ShortfallText {
  const returned = summary?.returned ?? 0
  const lines = (summary?.shortfall ?? []).map((l) => l.message)
  const top = [...(summary?.shortfall ?? [])].sort((a, b) => b.count - a.count)[0]
  return {
    link: summary && returned < size ? `Why only ${returned}?` : null,
    headline: `${returned} of ${size} found.`,
    lines,
    mostCommon: top?.message ?? null,
  }
}

export const SOURCE_NAMES: Record<string, string> = {
  commons: 'Wikimedia Commons',
  openverse: 'Openverse',
  met: 'the Met',
  aic: 'the Art Institute of Chicago',
  smithsonian: 'the Smithsonian',
}

export function sourceName(id: string): string {
  return SOURCE_NAMES[id] ?? id
}

const SOURCE_STATE: Record<LiveSourceStatus, string> = {
  ok: 'searched',
  failed: "didn't respond",
  timeout: 'timed out',
  skipped: 'skipped (cooling down)',
}

/** One "Name: state" line per live source, for the "Why only N?" summary. */
export function sourceStatusLines(live: LiveSummary | undefined): string[] {
  return Object.entries(live?.sources ?? {}).map(([id, st]) => `${sourceName(id)}: ${SOURCE_STATE[st] ?? st}`)
}

export function originLabel(c: { origin?: 'corpus' | 'live'; source?: string }): string {
  return c.origin === 'live' && c.source ? `Found live on ${sourceName(c.source)}` : 'From your library'
}

export function progressText(stage: string | undefined, validated = 0, shortlist = 0, live?: LiveProgress): string {
  switch (stage) {
    case 'searching': {
      const ids = live?.searching?.length ? live.searching : Object.keys(live?.sources ?? {})
      if (ids.length === 0) return 'Searching'
      const names = ids.slice(0, 2).map(sourceName).join(', ')
      const more = ids.length > 2 ? ', …' : ''
      const found = live?.found ? ` (found ${live.found})` : ''
      return `Searching ${names}${more}${found}`
    }
    case 'validating':
      return shortlist ? `Checking ${validated} of ${shortlist}` : 'Checking candidates'
    case 'retrieving':
      return 'Finding candidates'
    case 'completed':
      return 'Done'
    case 'failed':
      return 'Failed'
    default:
      return 'Starting'
  }
}

const RUN_ERRORS: Record<string, string> = {
  RUN_INTERRUPTED: 'it was interrupted before it finished',
  RUN_ERROR: 'something went wrong on the server',
  MODEL_TIMEOUT: 'the model timed out',
  MODEL_UNAVAILABLE: 'the model is unavailable',
}

export function runFailureText(code: string | null | undefined): string {
  const msg = (code && RUN_ERRORS[code]) || (code ? code.toLowerCase().replace(/_/g, ' ') : 'unknown error')
  return `This run failed: ${msg}.`
}

// ---- decisions ----

export const REJECT_REASON_LABELS: Record<string, string> = {
  wrong_target_change: 'Wrong change',
  protected_changed: 'Changed something I protected',
  image_quality: 'Image quality',
  not_on_brief: 'Not on brief',
  duplicate_feel: 'Feels like a duplicate',
  not_my_style: 'Not my style',
  other: 'Other',
}
export const NOTE_MAX = 500

export const verdictMark = (v: string) => (v === 'pass' ? '✓' : v === 'fail' ? '✕' : '?')

// ---- compare ----

export interface CompareInput {
  itemId: string
  attributes: readonly ItemAttribute[]
}

export interface CompareRow {
  key: string
  label: string
  kind: AttrKind
  values: AttrValue[]
}

const same = (a: AttrValue, b: AttrValue) => a === b

/** Attributes whose values are not all equal across the items (a missing value counts as unknown). */
export function compareDiff(items: readonly CompareInput[]): CompareRow[] {
  const order: ItemAttribute[] = []
  const seen = new Set<string>()
  for (const it of items)
    for (const a of it.attributes)
      if (!seen.has(a.key)) {
        seen.add(a.key)
        order.push(a)
      }
  const rows: CompareRow[] = []
  for (const a of order) {
    const values = items.map((it) => it.attributes.find((x) => x.key === a.key)?.value ?? null)
    if (values.every((v) => same(v, values[0]))) continue
    rows.push({ key: a.key, label: a.label, kind: a.kind, values })
  }
  return rows
}

/** Wire form of a value for target_values (the server canonicalises). */
export const valueToWire = (v: AttrValue): string => (v === null ? '' : String(v))
