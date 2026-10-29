import { type Exploration, type GeneratedCheck, type Item, isGenerated } from '../api'

export type VerdictTone = 'ok' | 'warn' | 'pending' | 'error'
export interface Verdict {
  text: string
  tone: VerdictTone
}

/** The one-line result of a generated image's check: did the target land, and what stayed. */
export function verdictText(
  check: GeneratedCheck | null,
  label: string,
  optionName: string,
  labels?: ReadonlyMap<string, string>,
): Verdict {
  if (!check) return { text: 'Checking…', tone: 'pending' }
  if (check.error) return { text: 'Check failed', tone: 'error' }
  const answer = check.target?.answer
  if (answer === 'no') return { text: `${label} didn't change to ${optionName}`, tone: 'warn' }
  if (answer !== 'yes') return { text: `${label}: unclear`, tone: 'warn' }
  const drifted = check.drifted ?? []
  let text = `${label} → ${optionName} ✓ · ${check.kept ?? 0} of ${check.of ?? 0} kept`
  if (drifted.length) text += ` · drifted: ${drifted.map((k) => labels?.get(k) ?? k).join(', ')}`
  if ((check.unknown ?? 0) > 0) text += ` · ${check.unknown} unclear`
  return { text, tone: drifted.length ? 'warn' : 'ok' }
}

/** The verdict for a generated item, looked up from its exploration option; null for other items. */
export function itemVerdict(
  item: Item,
  explorations: readonly Exploration[] | undefined,
  labels: ReadonlyMap<string, string>,
): (Verdict & { optionName: string }) | null {
  // plugin-generated images are never checked against an option: no verdict, not "Checking…"
  if (!isGenerated(item) || item.generation?.plugin) return null
  for (const e of explorations ?? []) {
    const option = e.options.find((o) => o.id === item.explore_option_id)
    if (option) {
      return { ...verdictText(item.check, labels.get(e.key) ?? e.key, option.name, labels), optionName: option.name }
    }
  }
  // exploration still loading or gone: a neutral, label-free verdict
  const c = item.check
  if (!c) return { text: 'Checking…', tone: 'pending', optionName: '' }
  if (c.error) return { text: 'Check failed', tone: 'error', optionName: '' }
  if (c.target?.answer === 'no') return { text: "Didn't change to the option", tone: 'warn', optionName: '' }
  if (c.target?.answer !== 'yes') return { text: 'Target unclear', tone: 'warn', optionName: '' }
  const drifted = c.drifted ?? []
  let text = `✓ · ${c.kept ?? 0} of ${c.of ?? 0} kept`
  if (drifted.length) text += ` · drifted: ${drifted.map((k) => labels.get(k) ?? k).join(', ')}`
  if ((c.unknown ?? 0) > 0) text += ` · ${c.unknown} unclear`
  return { text, tone: drifted.length ? 'warn' : 'ok', optionName: '' }
}
