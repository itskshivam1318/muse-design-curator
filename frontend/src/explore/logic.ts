/** Pure helpers behind the explore axes and the option notes. No React, no network. */
import { ApiError, type Exploration, type ExploreOption } from '../api'

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
