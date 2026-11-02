/** A note on the canvas: a warm paper card whose height follows its text. */
import { useMemo } from 'react'
import { Group, Rect, Text } from 'react-konva'
import type { Item } from '../api'
import { HIGHLIGHT_FILL, highlightBands, NOTE_FILL, NOTE_INK, NOTE_W, noteHeight, noteTextProps } from './noteSize'

interface Props {
  item: Item
  /** Konva handlers for the group (select, drag, hover, double-click). */
  events?: Record<string, unknown>
  draggable?: boolean
  /** Hidden while the HTML editor sits over it. */
  hidden?: boolean
  /** A passage [start, end) of the text to mark (a hovered part of the note). */
  highlight?: readonly [number, number] | null
}

export function NoteNode({ item, events, draggable = false, hidden = false, highlight = null }: Props) {
  const text = item.note_text ?? ''
  const height = useMemo(() => noteHeight(text), [text])
  const [hStart, hEnd] = highlight ?? [0, 0]
  const bands = useMemo(() => highlightBands(text, hStart, hEnd), [text, hStart, hEnd])
  return (
    <Group id={item.id} x={item.x} y={item.y} draggable={draggable} visible={!hidden} {...events}>
      <Rect
        name="note-card"
        width={NOTE_W}
        height={height}
        fill={NOTE_FILL}
        cornerRadius={4}
        shadowEnabled
        shadowColor="rgb(20,24,30)"
        shadowOpacity={0.12}
        shadowBlur={6}
        shadowOffsetY={2}
      />
      {bands.map((b, i) => (
        <Rect key={i} name="note-highlight" {...b} fill={HIGHLIGHT_FILL} cornerRadius={2} listening={false} />
      ))}
      <Text name="note-text" {...noteTextProps} text={text} fill={NOTE_INK} listening={false} />
    </Group>
  )
}
