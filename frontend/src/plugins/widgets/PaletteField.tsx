/** A named colour list: presets and the board's palettes to start from, one swatch at a time to edit, copy as hex. */
import { useState } from 'react'
import type { PalettePreset } from '../nodeLogic'

export interface PaletteValue {
  name?: string
  colors: string[]
}

interface Props {
  id: string
  value: unknown
  presets?: PalettePreset[]
  /** Palettes found on the board's items (hex lists). */
  boardPalettes?: string[][]
  minItems?: number
  maxItems?: number
  readOnly?: boolean
  onSave: (v: unknown) => void
}

const HEX = /^#[0-9a-fA-F]{6}$/
const same = (a: string[], b: string[]) => a.length === b.length && a.every((c, i) => c.toLowerCase() === b[i].toLowerCase())

function readPalette(v: unknown): PaletteValue {
  if (typeof v !== 'object' || v === null) return { colors: [] }
  const o = v as { name?: unknown; colors?: unknown }
  const colors = Array.isArray(o.colors) ? o.colors.filter((c): c is string => typeof c === 'string' && HEX.test(c)) : []
  return { name: typeof o.name === 'string' ? o.name : undefined, colors }
}

/** Board palettes without repeats, and without any a preset already covers. */
function distinctPalettes(lists: readonly string[][], presets: readonly PalettePreset[] = []): string[][] {
  const out: string[][] = []
  for (const l of lists) {
    const colors = l.filter((c) => HEX.test(c))
    if (colors.length < 2) continue
    if (presets.some((p) => same(p.colors, colors)) || out.some((o) => same(o, colors))) continue
    out.push(colors)
  }
  return out
}

function Strip({ colors }: { colors: string[] }) {
  return (
    <span className="node-strip" aria-hidden="true">
      {colors.map((c, i) => (
        <span key={i} style={{ background: c }} />
      ))}
    </span>
  )
}

export function PaletteField({ id, value, presets = [], boardPalettes = [], minItems = 2, maxItems = 8, readOnly, onSave }: Props) {
  const cur = readPalette(value)
  const [copied, setCopied] = useState(false)
  const board = distinctPalettes(boardPalettes, presets)
  const set = (colors: string[], name?: string) => onSave({ name: name ?? cur.name ?? 'Custom', colors })
  const copy = () => {
    const text = cur.colors.join(', ')
    void Promise.resolve(navigator.clipboard?.writeText(text)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div id={id} className="node-palette" role="group" aria-label="Palette">
      {presets.length > 0 && (
        <div className="node-palette-row" role="group" aria-label="Presets">
          {presets.map((p) => (
            <button key={p.name} type="button" className="node-palette-pick" disabled={readOnly} title={p.name} aria-label={`Preset ${p.name}`} onClick={() => set(p.colors, p.name)}>
              <Strip colors={p.colors} />
            </button>
          ))}
        </div>
      )}
      {board.length > 0 && (
        <div className="node-palette-row" role="group" aria-label="Board palettes">
          {board.map((c, i) => (
            <button key={i} type="button" className="node-palette-pick" disabled={readOnly} aria-label={`Board palette ${i + 1}`} onClick={() => set(c, 'Board')}>
              <Strip colors={c} />
            </button>
          ))}
        </div>
      )}
      <div className="node-palette-row" role="group" aria-label="Colours">
        {cur.colors.map((c, i) => (
          <span key={i} className="node-swatch">
            <input
              type="color"
              value={c.toLowerCase()}
              aria-label={`Colour ${i + 1}`}
              disabled={readOnly}
              onChange={(e) => set(cur.colors.map((x, j) => (j === i ? e.target.value : x)), 'Custom')}
            />
            {cur.colors.length > minItems && !readOnly && (
              <button type="button" className="node-swatch-x" aria-label={`Remove colour ${i + 1}`} onClick={() => set(cur.colors.filter((_, j) => j !== i), 'Custom')}>
                ×
              </button>
            )}
          </span>
        ))}
        {cur.colors.length < maxItems && (
          <button
            type="button"
            className="node-mini"
            disabled={readOnly}
            onClick={() => set([...cur.colors, cur.colors[cur.colors.length - 1] ?? '#808080'], 'Custom')}
          >
            Add colour
          </button>
        )}
      </div>
      <div className="node-palette-row">
        <span className="muted small">{cur.name ?? ''}</span>
        <button type="button" className="node-mini" disabled={cur.colors.length === 0} onClick={copy}>
          {copied ? 'Copied' : 'Copy hex'}
        </button>
      </div>
    </div>
  )
}
