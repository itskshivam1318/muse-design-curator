/** Pure helpers behind the Explore panel and the option notes. No React, no network. */
import { ApiError, type AttributeSpec, type Exploration, type ExploreOption, type VariationRequest } from '../api'
import { vocabularyOf } from '../vary/logic'

export interface OptionRow {
  option: ExploreOption
  depth: number
}

const byBatchThenCreation = (a: ExploreOption, b: ExploreOption) =>
  a.batch - b.batch || (a.created_at ?? '').localeCompare(b.created_at ?? '')

/**
 * The options in list order: by batch, then creation, each option's branches right after it
 * (one level deeper). Dismissed options are left out; a branch whose parent was dismissed
 * moves up to the top level so it stays visible.
 */
export function optionTree(options: ExploreOption[]): OptionRow[] {
  const live = options.filter((o) => o.status !== 'dismissed').sort(byBatchThenCreation)
  const ids = new Set(live.map((o) => o.id))
  const children = new Map<string, ExploreOption[]>()
  const roots: ExploreOption[] = []
  for (const o of live) {
    const parent = o.parent_option_id
    if (parent && ids.has(parent) && parent !== o.id) children.set(parent, [...(children.get(parent) ?? []), o])
    else roots.push(o)
  }
  const out: OptionRow[] = []
  const seen = new Set<string>()
  const walk = (o: ExploreOption, depth: number) => {
    if (seen.has(o.id)) return
    seen.add(o.id)
    out.push({ option: o, depth })
    for (const c of children.get(o.id) ?? []) walk(c, depth + 1)
  }
  roots.forEach((o) => walk(o, 0))
  return out
}

/**
 * Whether "Find real examples" can search for this option: it needs a value, and a closed
 * enum only matches values in its vocabulary (visualizing an option adds its value).
 */
export function canFindReal(spec: AttributeSpec, value: ExploreOption['value']): boolean {
  if (value === null || value === undefined) return false
  if (spec.kind !== 'enum' || spec.open_vocabulary === true) return true
  return vocabularyOf(spec).includes(String(value))
}

/** The variation run behind "Find real examples": prefer the option's value, keep what it keeps. */
export function findRealRequest(itemId: string, key: string, option: ExploreOption): VariationRequest {
  return {
    source_item_id: itemId,
    target_key: key,
    mode: 'prefer',
    target_values: [String(option.value)],
    protected_keys: option.keeps,
    nudge: null,
  }
}

/** The board's explorations with `e` added or replaced (the same merge as the explore.updated event). */
export function withExploration(list: Exploration[] | undefined, e: Exploration): Exploration[] {
  const all = list ?? []
  const at = all.findIndex((x) => x.id === e.id)
  if (at === -1) return [...all, e]
  const next = all.slice()
  next[at] = e
  return next
}

/** The board's explorations with one option replaced in place (after a PATCH or visualize). */
export function withOption(list: Exploration[] | undefined, option: ExploreOption): Exploration[] | undefined {
  return list?.map((e) =>
    e.id === option.exploration_id ? { ...e, options: e.options.map((o) => (o.id === option.id ? option : o)) } : e,
  )
}

/** A visualize refused because one is already running for the option: its job's events will follow. */
export const visualizeInProgress = (e: unknown): boolean =>
  e instanceof ApiError && e.status === 409 && e.code === 'VISUALIZE_IN_PROGRESS'
