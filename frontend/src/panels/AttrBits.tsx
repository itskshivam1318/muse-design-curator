import type { AttrValue } from '../api'
import { colorHex, formatValue } from '../vary/logic'

export function Swatch({ hex, label }: { hex: string | null; label?: string }) {
  if (!hex) return null
  return <i className="swatch" style={{ background: hex }} title={label ?? hex} aria-hidden="true" />
}

/** A value as words, with a swatch for colours. */
export function ValueText({
  kind,
  value,
  unit,
  measured,
}: {
  kind: string
  value: AttrValue
  unit?: string
  measured?: Record<string, unknown> | null
}) {
  return (
    <span className="value-text">
      {kind === 'color' && <Swatch hex={colorHex(value, measured)} />}
      {formatValue(value, unit)}
    </span>
  )
}

/** An ordinal scale, marking the current and target steps. */
export function ScaleView({
  scale,
  current,
  target,
  className = 'scale',
}: {
  scale: string[]
  current?: AttrValue
  target?: AttrValue
  className?: string
}) {
  return (
    <ol className={className} aria-label="Scale">
      {scale.map((s) => {
        const step = s === target ? 'target' : s === current ? 'current' : undefined
        return (
          <li key={s} data-step={step}>
            <span>{formatValue(s)}</span>
            {step === 'current' && <em> (now)</em>}
            {step === 'target' && <em> (target)</em>}
          </li>
        )
      })}
    </ol>
  )
}
