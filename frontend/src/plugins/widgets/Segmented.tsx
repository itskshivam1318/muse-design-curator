/** An enum as a row of radio buttons; an integer enum saves numbers. */
interface Props {
  id: string
  label: string
  options: string[]
  numeric?: boolean
  value: unknown
  readOnly?: boolean
  onSave: (v: unknown) => void
}

export function Segmented({ id, label, options, numeric, value, readOnly, onSave }: Props) {
  return (
    <div id={id} className="node-segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => {
        const on = String(value ?? '') === o
        return (
          <button
            key={o}
            type="button"
            role="radio"
            aria-checked={on}
            className={on ? 'is-on' : undefined}
            disabled={readOnly}
            onClick={() => !on && onSave(numeric ? Number(o) : o)}
          >
            {o}
          </button>
        )
      })}
    </div>
  )
}
