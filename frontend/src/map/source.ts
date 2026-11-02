/** Where an attribute's value came from, as a small mark shows it. */
import type { ItemAttribute } from '../api'

export type ChipSource = 'measured' | 'read' | 'estimated' | 'web' | 'you' | 'unknown'

export function chipSource(a: ItemAttribute): ChipSource {
  if (a.value === null || a.status === 'missing') return 'unknown'
  if (a.source === 'user' || a.status === 'edited' || a.status === 'confirmed') return 'you'
  if (a.measured) return 'measured'
  if (a.source === 'web' || a.source === 'live') return 'web'
  if (a.status === 'uncertain') return 'estimated'
  return 'read'
}
