import type { AttributeSpec, ItemAttribute, ItemAttributes, LensSpec } from '../api'

export const LENS_ATTRS: AttributeSpec[] = [
  { key: 'dial_color', label: 'Dial colour', category: 'dial', kind: 'color', part: 'watch_dial' },
  { key: 'case_finish', label: 'Case finish', category: 'case', kind: 'enum', vocabulary: ['brushed', 'polished'] },
  { key: 'legibility', label: 'Legibility', category: 'dial', kind: 'ordinal', scale: ['low', 'medium', 'high'] },
  { key: 'case_diameter', label: 'Case diameter', category: 'case', kind: 'number', unit: 'mm', min: 30, max: 46, tolerance: 1 },
  { key: 'date_window', label: 'Date window', category: 'dial', kind: 'boolean' },
]

export const LENS: LensSpec = { id: 'watch', domain: 'watch', label: 'Watch', origin: 'curated', parts: [], attributes: LENS_ATTRS, notes: [] }

const VALUES: Record<string, ItemAttribute['value']> = {
  dial_color: 'black', case_finish: 'brushed', legibility: 'medium', case_diameter: 40, date_window: false,
}

export function makeAttrs(over: Partial<Record<string, Partial<ItemAttribute>>> = {}): ItemAttributes {
  return {
    parse_status: 'completed',
    parse_error_code: null,
    lens: LENS,
    provider: { id: 'mock', model: null, is_mock: true },
    attributes: LENS_ATTRS.map((s) => ({
      key: s.key, label: s.label, category: s.category, kind: s.kind as ItemAttribute['kind'],
      part: (s.part as string) ?? null, value: VALUES[s.key], confidence: 0.9, status: 'extracted',
      source: 'model', enabled: true, ...(over[s.key] ?? {}),
    })),
  }
}
