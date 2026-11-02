/** Pure helpers for showing attribute values (Inspect, Compare, explore). No React, no network. */
import type { AttrKind, AttributeSpec, AttrValue, BoardProfile, ItemAttribute } from './api'

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

export const isBoardSignal = (key: string, profile: BoardProfile | null | undefined) =>
  (profile?.signals ?? []).some((s) => s.key === key)

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
