import type { BoardProfile } from '../api'
import { humanize } from '../format'

export interface Row {
  id: string
  group: 'signal' | 'tension' | 'counter'
  label: string
  value: string
  count?: string
  swatches?: string[]
}

export function signalRows(p: BoardProfile): Row[] {
  const rows: Row[] = []
  for (const s of p.signals) {
    const clusters = p.attributes[s.key]?.clusters ?? []
    rows.push({
      id: `signal:${s.key}`,
      group: 'signal',
      label: s.label,
      value: humanize(s.modal_value),
      count: `${Math.round(s.consistency * s.n_known)} of ${s.n_known}`,
      swatches: clusters.slice(0, 3).map((c) => c.hex),
    })
  }
  for (const t of p.tensions) {
    const n = p.attributes[t.key]?.n_known
    const parts = t.values.map((v, i) =>
      n ? `${v.replace(/_/g, ' ')} ${Math.round(t.shares[i] * n)}` : `${v.replace(/_/g, ' ')} ${Math.round(t.shares[i] * 100)}%`,
    )
    rows.push({ id: `tension:${t.key}`, group: 'tension', label: t.label, value: `${t.label}: ${parts.join(' · ')}` })
  }
  for (const c of p.counter_signals) {
    rows.push({
      id: `counter:${c.key}:${c.value}`,
      group: 'counter',
      label: c.label,
      value: humanize(c.value),
      count: `${c.counter_count} not-this`,
    })
  }
  return rows
}
