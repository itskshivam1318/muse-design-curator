import { useMemo, useState } from 'react'
import { ApiError, type AttributeSpec, type AttrValue, type ItemAttribute, type VariationRequest } from '../api'
import { useAttributes, useItems, useProfile } from '../queries'
import {
  canNudge,
  COLOR_TABLE,
  formatValue,
  isTension,
  modesFor,
  numberBounds,
  nudgeTarget,
  defaultSelection,
  orderProtected,
  protectAll,
  preflightSentence,
  scaleOf,
  sortTargets,
  vocabularyOf,
} from '../vary/logic'
import { startRun } from '../vary/startRun'
import { ScaleView, Swatch, ValueText } from './AttrBits'
import { itemTitle } from '../format'
import type { DrawerPanelProps } from './drawerRegistry'
import { PanelHead } from './PanelHead'

type Choice = 'explore' | 'prefer' | 'avoid' | 'more' | 'less'

const MODE_LABEL: Record<Choice, string> = {
  explore: 'Explore',
  prefer: 'Prefer',
  avoid: 'Avoid',
  more: 'More',
  less: 'Less',
}
const MODE_HINT: Record<Choice, string> = {
  explore: 'anything different',
  prefer: 'one of these values',
  avoid: 'not these values',
  more: 'a step up the scale',
  less: 'a step down the scale',
}

interface VaryParams {
  targetKey?: string
  mode?: 'explore' | 'prefer' | 'avoid'
  values?: string[]
}

/** Vary: pick one target, a mode, what stays protected, read the preflight sentence, Run. */
export function VaryPanel({ boardId, itemId, params, onClose }: DrawerPanelProps) {
  const preset = (params ?? {}) as VaryParams
  const attrsQ = useAttributes(itemId)
  const profile = useProfile(boardId).data?.profile
  const item = useItems(boardId).data?.find((i) => i.id === itemId)
  const lens = attrsQ.data?.lens ?? null
  const records = useMemo(() => attrsQ.data?.attributes ?? [], [attrsQ.data])
  const byKey = useMemo(() => new Map(records.map((r) => [r.key, r])), [records])

  const [targetKey, setTargetKey] = useState<string | null>(preset.targetKey ?? null)
  const [choice, setChoice] = useState<Choice>(preset.mode ?? 'explore')
  const [values, setValues] = useState<string[]>(preset.values ?? [])
  const [steps, setSteps] = useState<1 | 2>(1)
  // null = the defaults for the current target; a Set once the user has touched a chip
  const [chosen, setChosen] = useState<Set<string> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const targets = useMemo(() => sortTargets(lens?.attributes ?? [], profile), [lens, profile])
  const spec = targets.find((a) => a.key === targetKey)
  const rec = targetKey ? byKey.get(targetKey) : undefined
  const current = rec?.value ?? null
  const protectedRows = useMemo(
    () => (targetKey ? orderProtected(records, targetKey, profile) : []),
    [records, targetKey, profile],
  )
  const selected = chosen ?? defaultSelection(protectedRows)
  const protectedOn = protectedRows.filter((r) => selected.has(r.key))

  const pickTarget = (key: string) => {
    setTargetKey(key)
    setChosen(null)
    setValues([])
    setError(null)
    const kind = targets.find((a) => a.key === key)?.kind ?? ''
    if ((choice === 'more' || choice === 'less') && !canNudge(kind)) setChoice('explore')
  }

  const pickMode = (c: Choice) => {
    setChoice(c)
    setError(null)
    if (c === 'avoid' && values.length === 0 && targetKey) {
      // the board's counter-signals are the natural things to avoid
      const counter = (profile?.counter_signals ?? []).filter((s) => s.key === targetKey).map((s) => s.value)
      setValues(counter)
    }
  }

  const isNudge = choice === 'more' || choice === 'less'
  const nudge = isNudge ? { direction: choice, steps } : null
  const landing = spec && nudge ? nudgeTarget(spec, current, nudge.direction, nudge.steps) : null
  const edge = (dir: 'more' | 'less', n: 1 | 2) => !spec || !nudgeTarget(spec, current, dir, n).ok
  const unit = numberBounds(spec)?.unit

  const mode = isNudge ? 'nudge' : choice
  const sentence =
    spec &&
    preflightSentence({
      targetLabel: spec.label,
      mode,
      values,
      nudge,
      current,
      target: landing?.ok ? landing.value : null,
      unit,
      protectedLabels: protectedOn.map((r) => r.label),
    })
  const ready =
    !!spec &&
    (mode === 'explore' || ((mode === 'prefer' || mode === 'avoid') && values.length > 0) || (mode === 'nudge' && !!landing?.ok))

  const run = async () => {
    if (!spec || !ready) return
    const body: VariationRequest = {
      source_item_id: itemId,
      target_key: spec.key,
      mode,
      target_values: mode === 'prefer' || mode === 'avoid' ? values : [],
      protected_keys: protectedOn.map((r) => r.key),
      nudge,
    }
    setBusy(true)
    setError(null)
    try {
      await startRun(boardId, body)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : 'Could not start the run')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel vary-panel">
      <PanelHead eyebrow="Vary" title={item ? itemTitle(item) : 'Item'} onClose={onClose} />
      {attrsQ.isPending && <p className="muted panel-pad">Loading attributes…</p>}
      {attrsQ.isError && <p className="error panel-pad">Could not load attributes: {attrsQ.error.message}</p>}
      {attrsQ.isSuccess && !lens && <p className="muted panel-pad">Confirm this board's lens before varying an item.</p>}
      {lens && (
        <div className="panel-body">
          <section className="step">
            <h3 className="eyebrow">1 · What to change</h3>
            <div role="radiogroup" aria-label="Target attribute" className="target-list">
              {targets.map((a) => {
                const r = byKey.get(a.key)
                const disabled = r ? !r.enabled : false
                return (
                  <button
                    key={a.key}
                    type="button"
                    role="radio"
                    aria-checked={a.key === targetKey}
                    disabled={disabled}
                    className="target"
                    onClick={() => pickTarget(a.key)}
                  >
                    <span className="target-label">{a.label}</span>
                    {isTension(a.key, profile) && <span className="mark is-tension">tension</span>}
                    <span className="target-value">
                      {disabled ? 'disabled' : <ValueText kind={a.kind} value={r?.value ?? null} unit={numberBounds(a)?.unit} measured={r?.measured} />}
                    </span>
                  </button>
                )
              })}
            </div>
          </section>

          {spec && (
            <section className="step">
              <h3 className="eyebrow">2 · How</h3>
              <div role="radiogroup" aria-label="Mode" className="seg">
                {(modesFor(spec.kind).flatMap((m) => (m === 'nudge' ? (['more', 'less'] as Choice[]) : [m as Choice]))).map((c) => (
                  <button
                    key={c}
                    type="button"
                    role="radio"
                    aria-checked={choice === c}
                    disabled={(c === 'more' || c === 'less') && edge(c, 1)}
                    title={MODE_HINT[c]}
                    onClick={() => pickMode(c)}
                  >
                    {MODE_LABEL[c]}
                  </button>
                ))}
              </div>
              {(choice === 'prefer' || choice === 'avoid') && (
                <ValuePicker spec={spec} current={current} values={values} onChange={setValues} />
              )}
              {nudge && (
                <div className="nudge">
                  <div role="radiogroup" aria-label="Steps" className="seg small">
                    {([1, 2] as const).map((n) => (
                      <button
                        key={n}
                        type="button"
                        role="radio"
                        aria-checked={steps === n}
                        disabled={edge(nudge.direction, n)}
                        onClick={() => setSteps(n)}
                      >
                        {n === 1 ? '1 step' : '2 steps'}
                      </button>
                    ))}
                  </div>
                  {spec.kind === 'ordinal' ? (
                    <ScaleView scale={scaleOf(spec)} current={current} target={landing?.ok ? landing.value : undefined} />
                  ) : (
                    <NumberScale spec={spec} current={current} target={landing?.ok ? landing.value : null} />
                  )}
                </div>
              )}
            </section>
          )}

          {spec && (
            <section className="step">
              <h3 className="eyebrow">3 · Keep the same</h3>
              {protectedRows.length === 0 ? (
                <p className="muted small">Nothing else is known about this item, so nothing is protected.</p>
              ) : (
                <>
                <div className="row-end">
                  <button type="button" className="link-btn" onClick={() => setChosen(protectAll(protectedRows))}>
                    Protect all
                  </button>
                  <button type="button" className="link-btn" onClick={() => setChosen(new Set())}>
                    Clear
                  </button>
                </div>
                <ul className="protected-chips">
                  {protectedRows.map((r) => {
                    const on = selected.has(r.key)
                    return (
                      <li key={r.key}>
                        <button
                          type="button"
                          className={on ? 'pchip is-on' : 'pchip'}
                          aria-pressed={on}
                          aria-label={`${on ? 'Unprotect' : 'Protect'} ${r.label}`}
                          onClick={() =>
                            setChosen(() => {
                              const next = new Set(selected)
                              if (next.has(r.key)) next.delete(r.key)
                              else next.add(r.key)
                              return next
                            })
                          }
                        >
                          {r.isBoardSignal && <span className="signal-dot" title="Board signal" />}
                          {r.label}: <ValueText kind={r.kind} value={r.value} unit={numberBounds(lens.attributes.find((a) => a.key === r.key))?.unit} />
                        </button>
                      </li>
                    )
                  })}
                </ul>
                </>
              )}
            </section>
          )}

          {spec && (
            <section className="step preflight" aria-live="polite">
              <h3 className="eyebrow">4 · Check and run</h3>
              <p className="preflight-sentence">{sentence}</p>
              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}
              <div className="row-end">
                <button type="button" className="btn" onClick={() => void run()} disabled={!ready || busy}>
                  {busy ? 'Starting…' : 'Run'}
                </button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function NumberScale({ spec, current, target }: { spec: AttributeSpec; current: AttrValue; target: AttrValue }) {
  const b = numberBounds(spec)
  if (!b) return null
  return (
    <ol className="scale is-number" aria-label="Scale">
      <li>{formatValue(b.min, b.unit)}</li>
      <li data-step="current">
        <span>{formatValue(current, b.unit)}</span>
        <em> (now)</em>
      </li>
      <li data-step="target">
        <span>{formatValue(target, b.unit)}</span>
        <em> (target)</em>
      </li>
      <li>{formatValue(b.max, b.unit)}</li>
    </ol>
  )
}

/** Values for Prefer / Avoid, chosen the way the attribute's kind allows. */
function ValuePicker({
  spec,
  current,
  values,
  onChange,
}: {
  spec: AttributeSpec
  current: ItemAttribute['value']
  values: string[]
  onChange: (v: string[]) => void
}) {
  const toggle = (v: string) => onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v])
  const options: string[] =
    spec.kind === 'ordinal'
      ? scaleOf(spec)
      : spec.kind === 'enum'
        ? vocabularyOf(spec)
        : spec.kind === 'color'
          ? Object.keys(COLOR_TABLE)
          : spec.kind === 'boolean'
            ? ['true', 'false']
            : []
  if (options.length > 0) {
    return (
      <div className="value-chips" role="group" aria-label="Values">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="vchip"
            aria-pressed={values.includes(o)}
            onClick={() => (spec.kind === 'boolean' ? onChange(values[0] === o ? [] : [o]) : toggle(o))}
          >
            {spec.kind === 'color' && <Swatch hex={COLOR_TABLE[o]} />}
            {spec.kind === 'boolean' ? (o === 'true' ? 'Yes' : 'No') : formatValue(o)}
            {String(current) === o && <em> (now)</em>}
          </button>
        ))}
      </div>
    )
  }
  return <FreeValues kind={spec.kind} unit={numberBounds(spec)?.unit} values={values} onChange={onChange} />
}

function FreeValues({
  kind,
  unit,
  values,
  onChange,
}: {
  kind: string
  unit?: string
  values: string[]
  onChange: (v: string[]) => void
}) {
  const [raw, setRaw] = useState(values.join(', '))
  const isNumber = kind === 'number'
  return (
    <label className="value-input">
      <span className="muted small">{isNumber ? `Value${unit ? ` (${unit})` : ''}` : 'Values, separated by commas'}</span>
      <input
        type={isNumber ? 'number' : 'text'}
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value)
          const parts = isNumber ? [e.target.value.trim()] : e.target.value.split(',').map((s) => s.trim())
          onChange(parts.filter(Boolean))
        }}
      />
    </label>
  )
}
