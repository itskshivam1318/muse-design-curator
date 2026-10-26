import type { AttributeSpec, LensSpec } from '../api'

export const KIND_LABEL: Record<string, string> = {
  enum: 'Choices',
  ordinal: 'Scales',
  number: 'Measures',
  color: 'Colours',
  boolean: 'Yes / no',
  shape: 'Shapes',
  text: 'Text',
}

/** The pruning note for a part, e.g. "Part strap was found in 3 of 10 sample images; …". */
export function partNote(spec: LensSpec, partId: string): string | null {
  return spec.notes.find((n) => n.startsWith(`Part ${partId} `)) ?? null
}

export function groupByKind(attrs: AttributeSpec[]): [string, AttributeSpec[]][] {
  const groups = new Map<string, AttributeSpec[]>()
  for (const a of attrs) groups.set(a.kind, [...(groups.get(a.kind) ?? []), a])
  return [...groups]
}
