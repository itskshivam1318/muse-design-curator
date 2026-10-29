import Konva from 'konva'
import { useEffect, useRef, useState } from 'react'
import { Circle, Group, Image as KImage, Label, Line, Rect, Tag, Text } from 'react-konva'
import { type Item, itemImageUrl } from '../api'
import { useNoteVisualizing } from '../events'
import type { VerdictTone } from '../explore/verdict'
import { hostOf } from '../format'
import type { Bounds } from './geometry'
import {
  handleRects,
  hoverOutlineRect,
  imageNodeProps,
  isParsing,
  itemBounds,
  lineagePoints,
  SHIMMER_OPACITY,
  statusColor,
  statusDot,
  wantsFull,
} from './nodeProps'
import { NoteNode } from './NoteNode'
import type { CanvasPalette } from './palette'
import { useImage } from './useImage'

const KEPT_W = 38 // screen px
const GENERATED_W = 66 // screen px

const toneColor = (tone: VerdictTone | undefined, p: CanvasPalette) =>
  tone === 'ok' ? p.ok : tone === 'warn' ? p.warn : tone === 'error' ? p.bad : p.muted

type KEvent<E extends Event = MouseEvent> = Konva.KonvaEventObject<E>

export interface ItemHandlers {
  onPointerDown: (e: KEvent, item: Item) => void
  onDragStart: (e: KEvent<DragEvent>, item: Item) => void
  onDragMove: (e: KEvent<DragEvent>, item: Item) => void
  onDragEnd: (e: KEvent<DragEvent>, item: Item) => void
  onEnter: (item: Item) => void
  onLeave: (item: Item) => void
  /** Double-click / double-tap: open the item (Inspect). */
  onOpen?: (item: Item) => void
}

interface NodeProps {
  item: Item
  scale: number
  draggable: boolean
  palette: CanvasPalette
  handlers: ItemHandlers
  /** A note being edited in place: the HTML editor covers it, so it is not drawn. */
  hidden?: boolean
}

function common(item: Item, draggable: boolean, h: ItemHandlers) {
  return {
    draggable,
    onMouseDown: (e: KEvent) => h.onPointerDown(e, item),
    onTap: (e: KEvent<TouchEvent>) => h.onPointerDown(e as unknown as KEvent, item),
    onDragStart: (e: KEvent<DragEvent>) => h.onDragStart(e, item),
    onDragMove: (e: KEvent<DragEvent>) => h.onDragMove(e, item),
    onDragEnd: (e: KEvent<DragEvent>) => h.onDragEnd(e, item),
    onMouseEnter: () => h.onEnter(item),
    onMouseLeave: () => h.onLeave(item),
    onDblClick: () => h.onOpen?.(item),
    onDblTap: () => h.onOpen?.(item),
  }
}

/**
 * An image or video item: the bare picture, edge to edge. One stable Konva Image node: it hit-tests
 * its full bounds even before the bitmap loads, and keeps the previous bitmap while a new one loads
 * (e.g. after choosing another video frame), so hover state is never lost to a node swap.
 */
function PictureNode({ item, scale, draggable, handlers }: NodeProps) {
  const dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
  const thumb = useImage(itemImageUrl(item, 'thumb'))
  const full = useImage(wantsFull(item, scale, dpr) ? itemImageUrl(item, 'full') : null)
  const [shown, setShown] = useState<HTMLImageElement | undefined>(undefined)
  const image = full ?? thumb
  if (image && image !== shown) setShown(image)
  return <KImage {...imageNodeProps(item)} image={image ?? shown} {...common(item, draggable, handlers)} />
}

/**
 * A lettered square standing in for the site's icon. Deliberately not the real favicon: fetching
 * https://<host>/favicon.ico from the browser would contact a site the user only pasted.
 */
function SiteMark({ host, x, y, size, palette }: { host: string; x: number; y: number; size: number; palette: CanvasPalette }) {
  return (
    <Group x={x} y={y} listening={false}>
      <Rect width={size} height={size} cornerRadius={3} fill={palette.rule} />
      <Text width={size} height={size} align="center" verticalAlign="middle" text={host.charAt(0).toUpperCase()} fontSize={10} fontStyle="bold" fill={palette.ink} />
    </Group>
  )
}

/** A link that could not be unfurled: a text card that points to the extension. */
function LinkCard({ item, draggable, palette, handlers }: NodeProps) {
  const host = hostOf(item.page_url ?? item.source_url) ?? 'link'
  const title = item.page_title || item.page_url || item.source_url || ''
  const pad = 14
  const w = item.w || 240
  const h = item.h || 160
  return (
    <Group id={item.id} x={item.x} y={item.y} {...common(item, draggable, handlers)}>
      <Rect width={w} height={h} fill={palette.panel} stroke={palette.rule} strokeWidth={1} dash={[5, 4]} cornerRadius={6} />
      <SiteMark host={host} x={pad} y={pad} size={16} palette={palette} />
      <Text x={pad + 22} y={pad + 1} width={w - pad * 2 - 22} text={host} fontStyle="bold" fontSize={13} fill={palette.ink} ellipsis wrap="none" listening={false} />
      <Text x={pad} y={pad + 28} width={w - pad * 2} height={h - pad * 2 - 50} text={title} fontSize={12} lineHeight={1.35} fill={palette.muted} ellipsis listening={false} />
      <Text x={pad} y={h - pad - 14} width={w - pad * 2} text="Use the extension to capture this" fontSize={12} fill={palette.accent} listening={false} />
    </Group>
  )
}

export function ItemNode(props: NodeProps) {
  const { item, draggable, handlers, hidden } = props
  if (item.kind === 'note') return <NoteNode item={item} hidden={hidden} draggable={draggable} events={common(item, draggable, handlers)} />
  return item.kind === 'link' ? <LinkCard {...props} /> : <PictureNode {...props} />
}

// the server's placement of an image made from a note (backend IMAGE_GAP and STACK_GAP)
export const NOTE_IMAGE_GAP = 40
export const NOTE_STACK_GAP = 24
const PLACEHOLDER_W = 190
const PLACEHOLDER_H = 150
const TRACK_W = 120

interface VisualizingProps {
  note: Item
  /** Images already generated from this note: the next one lands below them. */
  siblings: readonly Item[]
  scale: number
  palette: CanvasPalette
  reduced: boolean
}

/** While a note is being visualized: a placeholder card where the image will land, tied by a dashed line. */
export function NoteVisualizing({ note, siblings, scale, palette, reduced }: VisualizingProps) {
  const visualizing = useNoteVisualizing(note.id)
  if (!visualizing) return null
  const x = note.x + note.w + NOTE_IMAGE_GAP
  const y = note.y + siblings.reduce((sum, s) => sum + s.h + NOTE_STACK_GAP, 0)
  const card = { x, y, width: PLACEHOLDER_W, height: PLACEHOLDER_H }
  return (
    <>
      <Line
        name="note-placeholder-line"
        points={lineagePoints(itemBounds(note), card)}
        bezier
        stroke={palette.noteEdge}
        strokeWidth={1.3 / scale}
        dash={[4 / scale, 4 / scale]}
        listening={false}
      />
      <Group name="note-placeholder" x={x} y={y} listening={false}>
        <Rect
          name="note-placeholder-card"
          width={PLACEHOLDER_W}
          height={PLACEHOLDER_H}
          cornerRadius={12}
          fill={palette.paper}
          stroke={palette.rule}
          strokeWidth={1.5}
        />
        <Progress x={(PLACEHOLDER_W - TRACK_W) / 2} y={PLACEHOLDER_H / 2 - 12} palette={palette} reduced={reduced} />
        <Text
          y={PLACEHOLDER_H / 2}
          width={PLACEHOLDER_W}
          align="center"
          text="Reading the board…"
          fontSize={12}
          fill={palette.muted}
        />
      </Group>
    </>
  )
}

/** An indeterminate 120×4 bar: a segment sweeps across; it rests at 55% when motion is reduced. */
function Progress({ x, y, palette, reduced }: { x: number; y: number; palette: CanvasPalette; reduced: boolean }) {
  const ref = useRef<Konva.Rect>(null)
  useEffect(() => {
    const node = ref.current
    if (!node || reduced) return
    const anim = new Konva.Animation((frame) => {
      if (!frame) return
      const phase = (frame.time / 1600) % 1
      node.x(-TRACK_W * 0.4 + phase * TRACK_W * 1.4)
    }, node.getLayer())
    anim.start()
    return () => {
      anim.stop()
    }
  }, [reduced])
  return (
    <Group x={x} y={y} clipX={0} clipY={0} clipWidth={TRACK_W} clipHeight={4}>
      <Rect width={TRACK_W} height={4} cornerRadius={2} fill={palette.rule} />
      <Rect
        ref={ref}
        name="note-placeholder-progress"
        width={TRACK_W * (reduced ? 0.55 : 0.4)}
        height={4}
        cornerRadius={2}
        fill={palette.accent}
      />
    </Group>
  )
}

/** A slow light band across a parsing image at 8% opacity; static when motion is reduced. */
export function Shimmer({ bounds, reduced }: { bounds: Bounds; reduced: boolean }) {
  const ref = useRef<Konva.Rect>(null)
  useEffect(() => {
    const node = ref.current
    if (!node || reduced) return
    const anim = new Konva.Animation((frame) => {
      if (!frame) return
      const w = node.width()
      const phase = ((frame.time / 2400) % 1) * 2 - 0.5 // -0.5 → 1.5 across the image
      node.fillLinearGradientStartPoint({ x: w * (phase - 0.3), y: 0 })
      node.fillLinearGradientEndPoint({ x: w * (phase + 0.3), y: 0 })
    }, node.getLayer())
    anim.start()
    return () => {
      anim.stop()
    }
  }, [reduced])
  return (
    <Rect
      ref={ref}
      x={bounds.x}
      y={bounds.y}
      width={bounds.width}
      height={bounds.height}
      opacity={SHIMMER_OPACITY}
      listening={false}
      fillLinearGradientStartPoint={{ x: 0, y: 0 }}
      fillLinearGradientEndPoint={{ x: bounds.width, y: 0 }}
      fillLinearGradientColorStops={
        reduced ? [0, '#ffffff', 1, '#ffffff'] : [0, 'rgba(255,255,255,0)', 0.5, '#ffffff', 1, 'rgba(255,255,255,0)']
      }
    />
  )
}

interface DecorProps {
  item: Item
  bounds: Bounds
  scale: number
  hovered: boolean
  selected: boolean
  reduced: boolean
  palette: CanvasPalette
  /** A generated item's check so far: tints its "generated" badge. */
  verdictTone?: VerdictTone
}

/** Everything drawn around an item: outline, status dot, handles, shimmer and small badges. */
export function ItemDecorations({ item, bounds, scale, hovered, selected, reduced, palette, verdictTone }: DecorProps) {
  const picture = item.kind === 'image' || item.kind === 'video'
  const parsing = picture && isParsing(item.parse_status)
  const showDot = picture && (hovered || item.parse_status !== 'completed')
  const badgeFont = 11 / scale
  const badgePad = 4 / scale
  const inset = 8 / scale
  return (
    <>
      {parsing && <Shimmer bounds={bounds} reduced={reduced} />}
      {(hovered || selected) && (
        <Rect name="item-outline" {...hoverOutlineRect(bounds, scale)} stroke={selected ? palette.accent : palette.ink} opacity={selected ? 1 : 0.55} />
      )}
      {showDot && <Circle {...statusDot(bounds, scale, selected)} fill={statusColor(item.parse_status, palette)} />}
      {selected &&
        handleRects(bounds, scale).map(({ key, ...h }) => (
          <Rect key={key} name="selection-handle" {...h} fill={palette.panel} stroke={palette.accent} />
        ))}
      {item.kind === 'video' && (hovered || selected) && (
        <Label x={bounds.x + inset} y={bounds.y + bounds.height - inset - badgeFont - badgePad * 2} listening={false}>
          <Tag fill="rgba(20,24,30,0.72)" cornerRadius={8 / scale} />
          <Text text="▶ video" fontSize={badgeFont} padding={badgePad} fill="#ffffff" />
        </Label>
      )}
      {item.role === 'counter_example' && (
        <Label x={bounds.x + inset} y={bounds.y + inset} listening={false}>
          <Tag fill={palette.bad} cornerRadius={8 / scale} />
          <Text text="Not this" fontSize={badgeFont} padding={badgePad} fill="#ffffff" />
        </Label>
      )}
      {item.origin === 'generated' && (
        <Label name="generated-badge" x={bounds.x + bounds.width - inset - GENERATED_W / scale} y={bounds.y + inset} listening={false}>
          <Tag fill={toneColor(verdictTone, palette)} cornerRadius={8 / scale} />
          <Text text="generated" width={GENERATED_W / scale} align="center" fontSize={badgeFont} padding={badgePad} fill="#ffffff" />
        </Label>
      )}
      {item.origin === 'candidate' && (
        <Label x={bounds.x + bounds.width - inset - KEPT_W / scale} y={bounds.y + inset} listening={false}>
          <Tag fill={palette.accent} cornerRadius={8 / scale} />
          <Text text="kept" width={KEPT_W / scale} align="center" fontSize={badgeFont} padding={badgePad} fill="#ffffff" />
        </Label>
      )}
    </>
  )
}
