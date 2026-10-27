import type { Item } from '../api'

/** Which images get a caption: the hovered one and every selected one (licensed or generated images). */
export function creditTargets(hovered: Item | undefined, selected: Item[]): Item[] {
  const out: Item[] = []
  for (const i of hovered ? [hovered, ...selected] : selected) {
    if (i.kind !== 'link' && (i.licence || i.generation) && !out.some((o) => o.id === i.id)) out.push(i)
  }
  return out
}
