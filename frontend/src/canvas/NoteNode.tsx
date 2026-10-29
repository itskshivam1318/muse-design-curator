/** A note on the canvas: a warm paper card whose height follows its text. */
import { useMemo } from 'react'
import { Group, Rect, Text } from 'react-konva'
import type { Item } from '../api'
import { NOTE_FILL, NOTE_INK, NOTE_W, noteHeight, noteTextProps } from './noteSize'

interface Props {
  item: Item
  /** Konva handlers for the group (select, drag, hover, double-click). */
  events?: Record<string, unknown>
  draggable?: boolean
  /** Hidden while the HTML editor sits over it. */
  hidden?: boolean
}

export function NoteNode({ item, events, draggable = false, hidden = false }: Props) {
  const text = item.note_text ?? ''
  const height = useMemo(() => noteHeight(text), [text])
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
      <Text name="note-text" {...noteTextProps} text={text} fill={NOTE_INK} listening={false} />
    </Group>
  )
}
