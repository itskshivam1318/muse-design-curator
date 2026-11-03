import type { AnalysisView, DimensionView } from '../api'

/** The item's own parts, each with the dimensions read from it, then the whole-item dimensions. */
export function inspectGroups(a: AnalysisView): { key: string; title: string; dims: DimensionView[] }[] {
  const partKeys = new Set(a.parts.map((p) => p.key))
  const groups = a.parts.map((p) => ({ key: p.key, title: p.label, dims: a.dimensions.filter((d) => d.part === p.key) }))
  // abstract dimensions, and any whose part has since been removed, describe the whole item
  const whole = a.dimensions.filter((d) => d.part === null || !partKeys.has(d.part))
  return whole.length > 0 ? [...groups, { key: '', title: 'Whole item', dims: whole }] : groups
}
