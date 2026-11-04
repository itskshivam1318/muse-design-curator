/** A native colour input that saves once per pick: the drag only moves a local draft; blur or the native `change` commits it. */
import { useEffect, useRef, useState } from 'react'

interface Props {
  value: string
  label: string
  disabled?: boolean
  onCommit: (hex: string) => void
}

export function ColorInput({ value, label, disabled, onCommit }: Props) {
  const [draft, setDraft] = useState(value)
  const [shownFor, setShownFor] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  const sent = useRef(value)
  const commitRef = useRef(onCommit)
  useEffect(() => {
    commitRef.current = onCommit
  })
  if (shownFor !== value) {
    setShownFor(value)
    setDraft(value)
  }
  useEffect(() => {
    sent.current = value
  }, [value])
  const commit = (hex: string) => {
    if (hex === sent.current) return
    sent.current = hex
    commitRef.current(hex)
  }
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const on = () => commit(el.value)
    el.addEventListener('change', on)
    return () => el.removeEventListener('change', on)
  }, [])
  return (
    <input
      ref={ref}
      type="color"
      value={draft}
      aria-label={label}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={(e) => commit(e.target.value)}
    />
  )
}
