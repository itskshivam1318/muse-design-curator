/** In-place editing of a note: an HTML textarea laid exactly over the note's card on screen. */
import { useLayoutEffect, useRef, useState } from 'react'
import type { Bounds } from './geometry'
import { NOTE_FILL, NOTE_FONT, NOTE_FONT_SIZE, NOTE_INK, NOTE_LINE_HEIGHT, NOTE_MIN_H, NOTE_PAD } from './noteSize'

/** The server's limit on a note's text. */
export const NOTE_MAX_CHARS = 2000

interface Props {
  /** The note's card in screen pixels (its top-left and width; the height grows with the text). */
  screen: Bounds
  scale: number
  initial: string
  /** Escape or leaving the field saves; called once with whatever was typed. */
  onCommit: (text: string) => void
}

export function NoteEditor({ screen, scale, initial, onCommit }: Props) {
  const [text, setText] = useState(initial)
  const ref = useRef<HTMLTextAreaElement>(null)
  const done = useRef(false)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }, [])

  // grow with the text, like the card it stands in for
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(NOTE_MIN_H * scale, el.scrollHeight)}px`
  }, [text, scale])

  const commit = () => {
    if (done.current) return
    done.current = true
    onCommit(text)
  }

  return (
    <textarea
      ref={ref}
      aria-label="Note"
      className="note-editor"
      value={text}
      maxLength={NOTE_MAX_CHARS}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        // Escape saves the note; it must not also close a panel or clear the selection
        e.preventDefault()
        e.stopPropagation()
        commit()
      }}
      style={{
        left: screen.x,
        top: screen.y,
        width: screen.width,
        minHeight: NOTE_MIN_H * scale,
        padding: NOTE_PAD * scale,
        fontSize: NOTE_FONT_SIZE * scale,
        lineHeight: NOTE_LINE_HEIGHT,
        fontFamily: NOTE_FONT,
        color: NOTE_INK,
        background: NOTE_FILL,
        borderRadius: 4 * scale,
      }}
    />
  )
}
