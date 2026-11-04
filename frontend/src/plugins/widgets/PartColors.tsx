/** A colour per mask part of the input item, saved as {part key: hex}. */
import { useAnalysis } from '../../queries'
import { ColorInput } from './ColorInput'

interface Props {
  id: string
  /** The input item whose parts are listed. */
  itemId: string | null
  value: unknown
  readOnly?: boolean
  onSave: (v: unknown) => void
}

const HEX = /^#[0-9a-fA-F]{6}$/

export function PartColors({ id, itemId, value, readOnly, onSave }: Props) {
  const parts = (useAnalysis(itemId).data?.parts ?? []).filter((p) => p.region_kind === 'mask')
  const cur: Record<string, string> =
    typeof value === 'object' && value !== null && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).filter((e): e is [string, string] => typeof e[1] === 'string' && HEX.test(e[1])))
      : {}
  const save = (next: Record<string, string>) => onSave(Object.keys(next).length ? next : undefined)
  if (itemId === null) return <p id={id} className="muted small">Add an image to colour its parts.</p>
  if (parts.length === 0) return <p id={id} className="muted small">This image has no parts to colour yet.</p>
  return (
    <ul id={id} className="node-parts">
      {parts.map((p) => (
        <li key={p.key}>
          <span>{p.label}</span>
          <ColorInput
            value={(cur[p.key] ?? '#808080').toLowerCase()}
            label={`${p.label} colour`}
            disabled={readOnly}
            onCommit={(hex) => save({ ...cur, [p.key]: hex })}
          />
          {p.key in cur && (
            <button
              type="button"
              className="node-mini"
              disabled={readOnly}
              aria-label={`Clear ${p.label} colour`}
              onClick={() => {
                const { [p.key]: _drop, ...rest } = cur
                save(rest)
              }}
            >
              Clear
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
