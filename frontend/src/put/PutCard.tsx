/**
 * The card on a "put into" line once it is let go: what goes where, one chip per spot (switch one off,
 * never the last), a few optional words, Cancel and Put in. Enter puts it in, Esc cancels. A refused
 * request shows its message here and the card stays.
 */
import { type FormEvent, type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ApiError, type Item } from '../api'
import { itemTitle } from '../format'
import { spotLabel, type Spot } from './spots'

const WORDS_MAX = 200

interface Props {
  source: Item
  target: Item
  spots: readonly Spot[]
  off: ReadonlySet<number>
  onToggle: (i: number) => void
  onCancel: () => void
  onSubmit: (words: string) => Promise<void>
  /** Its drawn size (screen px) whenever it changes; null once it closes. */
  onSize?: (size: { width: number; height: number } | null) => void
}

/** An item's title for the card; a picture with no name of its own is "Picture". */
const pictureTitle = (i: Item): string => {
  const t = itemTitle(i)
  return t === `${i.kind} item` ? 'Picture' : t
}

const errorText = (e: unknown, fallback: string) =>
  e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback

export function PutCard({ source, target, spots, off, onToggle, onCancel, onSubmit, onSize }: Props) {
  const [words, setWords] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // one request at a time, even when a second press lands before the re-render disables the button
  const inFlight = useRef(false)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => inputRef.current?.focus(), [])
  // measured like the selection toolbar: after every render (chips wrap, an error shows) and on resize
  const ref = useRef<HTMLFormElement>(null)
  const onSizeRef = useRef(onSize)
  useLayoutEffect(() => {
    onSizeRef.current = onSize
  })
  useLayoutEffect(() => {
    const el = ref.current
    if (el) onSizeRef.current?.({ width: el.offsetWidth, height: el.offsetHeight })
  })
  useEffect(() => {
    const el = ref.current
    const report = () => el && onSizeRef.current?.({ width: el.offsetWidth, height: el.offsetHeight })
    const ro = el && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(report) : null
    if (el) ro?.observe(el)
    return () => {
      ro?.disconnect()
      onSizeRef.current?.(null)
    }
  }, [])
  const onCount = spots.length - spots.filter((_, i) => off.has(i)).length

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    if (inFlight.current || onCount === 0) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await onSubmit(words)
    } catch (err) {
      setError(errorText(err, 'Could not put it in'))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    onCancel()
  }

  return (
    <form
      ref={ref}
      className="put-card"
      role="dialog"
      aria-label="Put in"
      onSubmit={(e) => void submit(e)}
      onKeyDown={onKeyDown}
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="put-card-title">
        {pictureTitle(source)} → {pictureTitle(target)}
      </p>
      <div className="put-chips">
        {spots.map((s, i) => {
          const on = !off.has(i)
          return (
            <button
              key={s.kind === 'part' ? s.part.key : `point-${i}`}
              type="button"
              className={on ? 'put-chip' : 'put-chip is-off'}
              aria-pressed={on}
              // the last spot on stays on
              disabled={busy || (on && onCount === 1)}
              onClick={() => onToggle(i)}
            >
              ✓ {spotLabel(s)}
            </button>
          )
        })}
      </div>
      <input
        ref={inputRef}
        className="put-words"
        type="text"
        value={words}
        maxLength={WORDS_MAX}
        placeholder="Anything to add? (optional)"
        aria-label="Anything to add? (optional)"
        onChange={(e) => setWords(e.target.value)}
      />
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="put-card-row">
        <button type="button" className="petal-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="petal-primary" disabled={busy || onCount === 0}>
          Put in
        </button>
      </div>
    </form>
  )
}
