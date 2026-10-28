import type Konva from 'konva'
import { Group, Rect, Text } from 'react-konva'
import type { Distance, ExploreOption, Point } from '../api'
import { hoverStore, setHoveredOption, useHoveredOption } from '../explore/hover'
import { NOTE_H, NOTE_W } from './notes'
import type { CanvasPalette } from './palette'

type KEvent<E extends Event = MouseEvent> = Konva.KonvaEventObject<E>

const PAD = 12
const DESC_FONT = 12
const DESC_LINE = 1.25
const CLOSE = 20

const distanceColor = (d: Distance, p: CanvasPalette) => (d === 'near' ? p.ok : d === 'bold' ? p.warn : p.bad)

interface Props {
  option: ExploreOption
  x: number
  y: number
  scale: number
  palette: CanvasPalette
  /** False in the locked demo: no dragging and no ×. */
  editable: boolean
  /** Space held: the stage pans instead of the note moving. */
  panning?: boolean
  onOpen: (option: ExploreOption) => void
  onDragMove: (option: ExploreOption, at: Point) => void
  /** Drag end: where the note was drawn before and where it was dropped (whole canvas px). */
  onMove: (option: ExploreOption, from: Point, to: Point) => void
  onDismiss: (option: ExploreOption) => void
}

/** An explore option as a card beside its source: name, distance, two lines of description. */
export function OptionNote({ option, x, y, scale, palette, editable, panning = false, onOpen, onDragMove, onMove, onDismiss }: Props) {
  const hovered = useHoveredOption() === option.id
  const stop = (e: KEvent<MouseEvent | DragEvent>) => {
    e.cancelBubble = true
  }
  return (
    <Group
      name="option-note"
      x={x}
      y={y}
      draggable={editable && !panning}
      onMouseDown={stop}
      onMouseEnter={() => setHoveredOption(option.id)}
      onMouseLeave={() => {
        if (hoverStore.get() === option.id) setHoveredOption(null)
      }}
      onClick={(e) => {
        stop(e)
        onOpen(option)
      }}
      onDragStart={stop}
      onDragMove={(e) => {
        stop(e)
        onDragMove(option, { x: e.target.x(), y: e.target.y() })
      }}
      onDragEnd={(e) => {
        stop(e)
        const to = { x: Math.round(e.target.x()), y: Math.round(e.target.y()) }
        // the cache drives the position: snap back to the props and let the save move the note
        e.target.position({ x, y })
        onMove(option, { x, y }, to)
      }}
    >
      <Rect
        name="note-card"
        width={NOTE_W}
        height={NOTE_H}
        cornerRadius={6}
        fill={palette.note}
        stroke={hovered ? palette.accent : palette.noteEdge}
        strokeWidth={(hovered ? 2 : 1) / scale}
        shadowEnabled={false}
      />
      <Text
        name="note-name"
        x={PAD}
        y={PAD}
        width={NOTE_W - PAD * 2 - (editable ? CLOSE : 0)}
        text={option.name}
        fontSize={13}
        fontStyle="bold"
        fill={palette.ink}
        wrap="none"
        ellipsis
        listening={false}
      />
      <Text
        name="note-distance"
        x={PAD}
        y={PAD + 19}
        text={option.distance}
        fontSize={10}
        fill={distanceColor(option.distance, palette)}
        listening={false}
      />
      {(option.status === 'visualizing' || option.last_error) && (
        <Text
          name="note-state"
          x={PAD}
          y={PAD + 19}
          width={NOTE_W - PAD * 2}
          align="right"
          text={option.status === 'visualizing' ? 'visualizing…' : "couldn't visualize"}
          fontSize={10}
          fill={option.status === 'visualizing' ? palette.muted : palette.bad}
          wrap="none"
          listening={false}
        />
      )}
      <Text
        name="note-desc"
        x={PAD}
        y={PAD + 36}
        width={NOTE_W - PAD * 2}
        height={2 * DESC_FONT * DESC_LINE}
        text={option.description}
        fontSize={DESC_FONT}
        lineHeight={DESC_LINE}
        fill={palette.muted}
        wrap="word"
        ellipsis
        listening={false}
      />
      {editable && (
        <Group
          name="note-dismiss"
          x={NOTE_W - PAD / 2 - CLOSE}
          y={PAD / 2}
          onClick={(e) => {
            stop(e)
            onDismiss(option)
          }}
        >
          <Rect width={CLOSE} height={CLOSE} fill="transparent" />
          <Text width={CLOSE} height={CLOSE} text="×" fontSize={16} align="center" verticalAlign="middle" fill={palette.muted} listening={false} />
        </Group>
      )}
    </Group>
  )
}
