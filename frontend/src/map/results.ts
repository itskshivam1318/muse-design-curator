/** A petal's result: which item it is, and where a rewritten text changed. */
import type { ExploreOption, Item } from '../api'

/** The option's result: its kept item, else its newest take that has arrived. */
export function resultOf(option: ExploreOption, byId: ReadonlyMap<string, Item>): Item | undefined {
  if (option.kept_item_id) return byId.get(option.kept_item_id)
  for (let i = option.takes.length - 1; i >= 0; i--) {
    const t = byId.get(option.takes[i])
    if (t) return t
  }
  return undefined
}

/** A rewritten text around its change: the changed span (common prefix and suffix trimmed) with a little context. */
export function changeExcerpt(before: string, after: string, context = 40): { pre: string; mark: string; post: string } {
  let p = 0
  while (p < before.length && p < after.length && before[p] === after[p]) p++
  let s = 0
  while (s < before.length - p && s < after.length - p && before[before.length - 1 - s] === after[after.length - 1 - s]) s++
  const end = after.length - s
  const from = Math.max(0, p - context)
  const to = Math.min(after.length, end + context)
  return {
    pre: (from > 0 ? '…' : '') + after.slice(from, p),
    mark: after.slice(p, end),
    post: after.slice(end, to) + (to < after.length ? '…' : ''),
  }
}

/** The one definition of a kept petal (its size, border, the hub's count): its option has a kept result. */
export const isKept = (option: ExploreOption): boolean => !!option.kept_item_id
