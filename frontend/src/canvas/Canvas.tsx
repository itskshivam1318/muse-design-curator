import type Konva from 'konva'
import {
  type DragEvent as ReactDragEvent,
  type Ref,
  type WheelEvent as ReactWheelEvent,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Layer, Line, Rect, Stage } from 'react-konva'
import { isGenerated, type Item, type Point, type UploadOrigin } from '../api'
import { useDemo } from '../demo'
import { itemVerdict } from '../explore/verdict'
import { useBoardLens, useExplorations, visibleItems } from '../queries'
import { setTool, useTool } from '../shell/tools'
import type { ItemActions } from './actions'
import { drawnAxes, keptFollowers, rowBounds } from './axis'
import { AxisLayer } from './AxisLayer'
import { handleDrop } from './drop'
import { FramesStrip } from './FramesStrip'
import {
  type Bounds,
  centeredView,
  fitView,
  normalizeRect,
  rectsIntersect,
  toCanvasPoint,
  toScreenBounds,
  unionBounds,
  type View,
  wheelZoomFactor,
  zoomAt,
} from './geometry'
import type { Move } from './history'
import { ItemDecorations, type ItemHandlers, ItemNode, NoteVisualizing } from './ItemNode'
import { CreditCaption } from './CreditCaption'
import { creditTargets } from './credit'
import { AxisPicker, ItemChips } from './ItemChips'
import { ItemToolbar } from './ItemToolbar'
import { itemBounds, lineagePoints, statusLabel } from './nodeProps'
import { NoteBar } from './NoteBar'
import { NoteEditor } from './NoteEditor'
import { NOTE_MIN_H, NOTE_W, noteHeight, sizedNote } from './noteSize'
import { useCanvasPalette, usePrefersReducedMotion } from './palette'
import { selection, useSelection } from './selection'

export interface CanvasHandle {
  fit: () => void
  /** The canvas point at the centre of the viewport (where pastes and menu uploads land). */
  center: () => Point
  /** Where an item's bounds sit on the page (client coordinates), e.g. for the Keep fly-in. */
  clientRectOf: (item: Item) => Bounds | null
  /** Pan (keeping the zoom) so the item sits at the viewport centre, e.g. when picked in Library. */
  centerOn: (item: Item) => void
}

interface Props {
  boardId: string
  items: Item[]
  actions: ItemActions
  onFiles: (files: File[], at: Point, origin: UploadOrigin) => void
  onOpenPanel: (kind: 'explore' | 'vary' | 'inspect' | 'compare', itemId: string, params?: Record<string, unknown>) => void
  spaceDown: boolean
  ref?: Ref<CanvasHandle>
  /** Public demo, not unlocked: no file drops, role changes, removal, frame choice or note edits. */
  readOnly?: boolean
  /** A note's ⋯ → Send to node (wired by the plugin nodes; the entries are hidden without it). */
  onSendToNode?: (pluginId: string, noteId: string) => void
}

/** A note being typed: a new one (no id yet, placed at `at`) or an existing one. */
type Editing = { id: null; at: Point } | { id: string }

type KEvent<E extends Event = MouseEvent> = Konva.KonvaEventObject<E>

const GRID = 24

/** Keep fitted items clear of the stage's rounded edge and the bottom toolbar. */
function fitInsets(width: number) {
  return width > 900 ? { top: 48, right: 48, bottom: 96, left: 48 } : { top: 24, right: 24, bottom: 96, left: 24 }
}

function useSize(el: HTMLElement | null) {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    if (!el) return
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return size
}

export function Canvas({
  boardId,
  items: allItems,
  actions,
  onFiles,
  onOpenPanel,
  spaceDown,
  ref,
  readOnly = false,
  onSendToNode,
}: Props) {
  const { exploreEnabled } = useDemo()
  // staged takes and plugin results wait elsewhere; notes are drawn at the size their text needs
  const visible = useMemo(() => visibleItems(allItems).map(sizedNote), [allItems])
  const tool = useTool()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [noteHover, setNoteHover] = useState<string | null>(null)
  const noteHoverTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const overNoteBar = useRef(false)
  const [container, setContainer] = useState<HTMLDivElement | null>(null)
  const size = useSize(container)
  const stageRef = useRef<Konva.Stage>(null)
  const [view, setView] = useState<View>({ x: 80, y: 80, scale: 1 })
  const viewRef = useRef(view)
  useLayoutEffect(() => {
    viewRef.current = view
  }, [view])
  const [hovered, setHovered] = useState<string | null>(null)
  const [stripFor, setStripFor] = useState<string | null>(null)
  const stripTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const overStrip = useRef(false)
  const [overrides, setOverrides] = useState<Record<string, Point>>({})
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])
  // explore off: no axes (the server lists no explorations either)
  const shownExplorations = useMemo(() => (exploreEnabled ? (explorations ?? []) : []), [exploreEnabled, explorations])
  // a kept take is drawn as its axis card, not loose: it moves with its source
  const axisInfo = useMemo(() => drawnAxes(visible, shownExplorations, labels), [visible, shownExplorations, labels])
  const items = useMemo(() => visible.filter((i) => !axisInfo.hidden.has(i.id)), [visible, axisInfo])
  const visibleById = useMemo(() => new Map(visible.map((i) => [i.id, i])), [visible])
  const dragStart = useRef<Map<string, Point> | null>(null)
  const [marquee, setMarquee] = useState<{ a: Point; b: Point; additive: boolean } | null>(null)
  const [dropActive, setDropActive] = useState(false)
  const pinch = useRef<{ dist: number; center: Point } | null>(null)
  const { selected } = useSelection()
  const palette = useCanvasPalette()
  const reduced = usePrefersReducedMotion()
  const fitted = useRef(false)

  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])
  const positioned = useCallback(
    (i: Item): Item => (overrides[i.id] ? { ...i, ...overrides[i.id] } : i),
    [overrides],
  )
  const ordered = useMemo(
    () => [...items].sort((a, b) => a.z - b.z || a.created_at.localeCompare(b.created_at)),
    [items],
  )

  useEffect(() => {
    selection.retain(new Set(byId.keys()))
  }, [byId])

  const fit = useCallback(() => {
    if (size.width === 0) return
    const axes = axisInfo.axes.flatMap((a) => a.rows.map(rowBounds))
    setView(fitView([...items.map(itemBounds), ...axes], size, fitInsets(size.width)))
  }, [items, axisInfo, size])

  // fit when the board's items first arrive, and when an empty board gets its first batch
  useEffect(() => {
    if (size.width === 0) return
    if (items.length === 0) {
      fitted.current = false
      return
    }
    if (fitted.current) return
    const t = setTimeout(() => {
      fitted.current = true
      fit()
    }, 300) // let a batch of item.added events settle first
    return () => clearTimeout(t)
  }, [items.length, size.width, fit])

  useImperativeHandle(
    ref,
    () => ({
      fit,
      center: () => toCanvasPoint({ x: size.width / 2, y: size.height / 2 }, viewRef.current),
      clientRectOf: (item: Item) => {
        if (!container) return null
        const r = container.getBoundingClientRect()
        const b = toScreenBounds(itemBounds(item), viewRef.current)
        return { ...b, x: b.x + r.left, y: b.y + r.top }
      },
      centerOn: (item: Item) => setView((v) => centeredView(v, itemBounds(item), size)),
    }),
    [fit, size, container],
  )

  // ---- pan & zoom ----
  const wheel = (evt: { ctrlKey: boolean; metaKey: boolean; deltaX: number; deltaY: number }, pointer: Point) => {
    if (evt.ctrlKey || evt.metaKey) {
      // ctrl+wheel, or a trackpad pinch (browsers report pinches as ctrl+wheel)
      setView((v) => zoomAt(v, pointer, v.scale * wheelZoomFactor(evt.deltaY)))
    } else {
      // two-finger scroll pans
      setView((v) => ({ ...v, x: v.x - evt.deltaX, y: v.y - evt.deltaY }))
    }
  }
  const onWheel = (e: KEvent<WheelEvent>) => {
    e.evt.preventDefault()
    const stage = stageRef.current
    wheel(e.evt, stage?.getPointerPosition() ?? { x: size.width / 2, y: size.height / 2 })
  }
  // over the axis cards (HTML above the stage) the wheel still pans and zooms the canvas
  const onOverlayWheel = (e: ReactWheelEvent) => {
    if (!container || (e.target as HTMLElement).closest('.axis-popover')) return
    const r = container.getBoundingClientRect()
    wheel(e, { x: e.clientX - r.left, y: e.clientY - r.top })
  }

  const onStageDrag = (e: KEvent<DragEvent>) => {
    if (e.target !== stageRef.current) return
    setView((v) => ({ ...v, x: e.target.x(), y: e.target.y() }))
  }

  const onTouchMove = (e: KEvent<TouchEvent>) => {
    const t = e.evt.touches
    if (t.length !== 2 || !container) return
    e.evt.preventDefault()
    const r = container.getBoundingClientRect()
    const p1 = { x: t[0].clientX - r.left, y: t[0].clientY - r.top }
    const p2 = { x: t[1].clientX - r.left, y: t[1].clientY - r.top }
    const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y)
    const center = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }
    const last = pinch.current
    pinch.current = { dist, center }
    if (!last) return
    setView((v) => {
      const zoomed = zoomAt(v, center, v.scale * (dist / last.dist))
      return { ...zoomed, x: zoomed.x + center.x - last.center.x, y: zoomed.y + center.y - last.center.y }
    })
  }

  // ---- marquee & empty clicks ----
  const pointerCanvas = (): Point | null => {
    const p = stageRef.current?.getPointerPosition()
    return p ? toCanvasPoint(p, viewRef.current) : null
  }

  const onStageDown = (e: KEvent) => {
    if (e.target !== stageRef.current || spaceDown || e.evt.button !== 0) return
    if (tool === 'note') {
      e.evt.preventDefault() // keep the mousedown from taking focus away from the editor about to open
      const p = pointerCanvas()
      if (readOnly || !p) return
      setTool('select')
      setEditing({ id: null, at: p })
      return
    }
    const p = pointerCanvas()
    if (p) setMarquee({ a: p, b: p, additive: e.evt.shiftKey })
  }
  const onStageMove = () => {
    if (!marquee) return
    const p = pointerCanvas()
    if (p) setMarquee((m) => (m ? { ...m, b: p } : m))
  }
  const onStageUp = () => {
    if (!marquee) return
    const r = normalizeRect(marquee.a, marquee.b)
    const tiny = r.width * view.scale < 3 && r.height * view.scale < 3
    const hits = tiny ? [] : items.filter((i) => rectsIntersect(r, itemBounds(i))).map((i) => i.id)
    if (marquee.additive) selection.add(hits)
    else selection.select(hits)
    setMarquee(null)
  }
  // end the marquee on any mouseup, including one released over a floating panel
  const endMarquee = useRef(onStageUp)
  useLayoutEffect(() => {
    endMarquee.current = onStageUp
  })
  const marqueeActive = marquee !== null
  useEffect(() => {
    if (!marqueeActive) return
    const up = () => endMarquee.current()
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
  }, [marqueeActive])

  // ---- item interaction ----
  const handlers: ItemHandlers = {
    onPointerDown: (e, item) => {
      e.cancelBubble = true
      if (e.evt.shiftKey) selection.toggle(item.id)
      else if (!selected.includes(item.id)) selection.select([item.id])
    },
    onDragStart: (e, item) => {
      e.cancelBubble = true
      const picked = selected.includes(item.id) ? selected : [item.id]
      if (!selected.includes(item.id)) selection.select([item.id])
      // a source carries the kept takes on its axes along, in the same move (one undo entry)
      const ids = [...picked, ...keptFollowers(axisInfo.axes, new Set(picked), visibleById)]
      dragStart.current = new Map(
        ids.flatMap((id) => {
          const it = visibleById.get(id)
          return it ? [[id, { x: it.x, y: it.y }] as const] : []
        }),
      )
    },
    onDragMove: (e, item) => {
      e.cancelBubble = true
      const starts = dragStart.current
      const s = starts?.get(item.id)
      if (!starts || !s) return
      const dx = e.target.x() - s.x
      const dy = e.target.y() - s.y
      const next: Record<string, Point> = {}
      for (const [id, p] of starts) next[id] = { x: p.x + dx, y: p.y + dy }
      setOverrides(next)
    },
    onDragEnd: (e, item) => {
      e.cancelBubble = true
      const starts = dragStart.current
      const s = starts?.get(item.id)
      dragStart.current = null
      if (!starts || !s) return
      const dx = e.target.x() - s.x
      const dy = e.target.y() - s.y
      const moves: Move[] = [...starts].map(([id, from]) => ({
        id,
        from,
        to: { x: Math.round(from.x + dx), y: Math.round(from.y + dy) },
      }))
      actions.move(moves)
      setOverrides({})
    },
    onOpen: (item) => {
      if (item.kind === 'note') {
        if (!readOnly) setEditing({ id: item.id })
      } else if (item.kind !== 'link') onOpenPanel('inspect', item.id)
    },
    onEnter: (item) => {
      setHovered(item.id)
      if (item.kind === 'note') {
        clearTimeout(noteHoverTimer.current)
        setNoteHover(item.id)
      }
      if (item.kind === 'video') {
        clearTimeout(stripTimer.current)
        setStripFor(item.id)
      }
    },
    onLeave: (item) => {
      setHovered((h) => (h === item.id ? null : h))
      if (item.kind === 'note') {
        clearTimeout(noteHoverTimer.current)
        noteHoverTimer.current = setTimeout(() => !overNoteBar.current && setNoteHover(null), 250)
      }
      if (item.kind === 'video') {
        clearTimeout(stripTimer.current)
        stripTimer.current = setTimeout(() => !overStrip.current && setStripFor(null), 250)
      }
    },
  }

  // ---- files dropped from the desktop ----
  // a file dropped on a floating panel must not make the browser navigate away to it
  useEffect(() => {
    const guard = (e: DragEvent) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
    }
    window.addEventListener('dragover', guard)
    window.addEventListener('drop', guard)
    return () => {
      window.removeEventListener('dragover', guard)
      window.removeEventListener('drop', guard)
    }
  }, [])
  const onDragOver = (e: ReactDragEvent) => {
    if (readOnly || !Array.from(e.dataTransfer.types).includes('Files')) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    setDropActive(true)
  }
  const onDrop = (e: ReactDragEvent) => {
    setDropActive(false)
    if (readOnly || !container || e.dataTransfer.files.length === 0) return
    e.preventDefault()
    handleDrop(
      {
        clientX: e.clientX,
        clientY: e.clientY,
        containerRect: container.getBoundingClientRect(),
        view: viewRef.current,
        files: Array.from(e.dataTransfer.files),
      },
      onFiles,
    )
  }

  // ---- derived overlay geometry ----
  const selectedItems = selected.flatMap((id) => {
    const it = byId.get(id)
    return it ? [positioned(it)] : []
  })
  const selBounds = unionBounds(selectedItems.map(itemBounds))
  const dragging = Object.keys(overrides).length > 0
  const stripItem = stripFor ? byId.get(stripFor) : undefined
  const hoveredItem = hovered ? byId.get(hovered) : undefined
  // an image made from a note always shows the solid line back to it (its provenance)
  const fromNote = (child: Item) => isGenerated(child) && byId.get(child.parent_item_id ?? '')?.kind === 'note'
  const noteLineage = items.flatMap((child) => {
    if (!fromNote(child)) return []
    const parent = byId.get(child.parent_item_id!)!
    return [{ id: child.id, points: lineagePoints(itemBounds(positioned(parent)), itemBounds(positioned(child))) }]
  })
  const noteChildren = (noteId: string) => items.filter((i) => i.parent_item_id === noteId && isGenerated(i))
  const lineage = items.flatMap((child) => {
    const parent = child.parent_item_id ? byId.get(child.parent_item_id) : undefined
    if (!parent || fromNote(child) || !(selected.includes(child.id) || selected.includes(parent.id))) return []
    return [{ id: child.id, points: lineagePoints(itemBounds(positioned(parent)), itemBounds(positioned(child))) }]
  })
  // the axes follow a dragged source (and its kept takes) while the drag is under way
  const axisItems = visible.map(positioned)
  // ---- notes: the editor and the bar ----
  const editedNote = editing?.id ? byId.get(editing.id) : undefined
  const editorAt: { x: number; y: number; text: string } | null = editing
    ? editing.id === null
      ? { ...editing.at, text: '' }
      : editedNote
        ? { x: editedNote.x, y: editedNote.y, text: editedNote.note_text ?? '' }
        : null
    : null
  const commitNote = (text: string) => {
    const e = editing
    setEditing(null)
    if (!e) return
    const clean = text.trim()
    const h = noteHeight(clean)
    if (e.id === null) {
      if (clean) void actions.createNote({ ...e.at, w: NOTE_W, h }, clean)
      return
    }
    const note = byId.get(e.id)
    // an emptied note keeps its old text; deleting is in its menu
    if (note && clean && clean !== note.note_text) actions.editNote(note, clean, h)
  }
  const soleSelected = selectedItems.length === 1 ? selectedItems[0] : undefined
  const barNote = [noteHover ? byId.get(noteHover) : undefined, soleSelected].find(
    (n): n is Item => !!n && n.kind === 'note' && n.id !== editing?.id,
  )
  const onlyNotes = selectedItems.length > 0 && selectedItems.every((i) => i.kind === 'note')
  const addNoteAtCenter = () => {
    const c = toCanvasPoint({ x: size.width / 2, y: size.height / 2 }, viewRef.current)
    setTool('select')
    setEditing({ id: null, at: { x: c.x - NOTE_W / 2, y: c.y - NOTE_MIN_H / 2 } })
  }

  const gridStep = GRID * view.scale * (view.scale < 0.5 ? 4 : view.scale < 1 ? 2 : 1)

  return (
    <div
      ref={setContainer}
      className={`canvas${dropActive ? ' is-drop' : ''}${spaceDown ? ' is-pan' : ''}${tool === 'note' && !readOnly ? ' is-note' : ''}`}
      style={{
        backgroundSize: `${gridStep}px ${gridStep}px`,
        backgroundPosition: `${view.x}px ${view.y}px`,
      }}
      role="region"
      aria-label={`Board canvas, ${items.length} ${items.length === 1 ? 'item' : 'items'}, zoom ${Math.round(view.scale * 100)}%`}
      aria-describedby="canvas-help"
      onDragOver={onDragOver}
      onDragLeave={() => setDropActive(false)}
      onDrop={onDrop}
    >
      <p id="canvas-help" className="sr-only">
        Space and drag or two-finger scroll to pan; control and scroll or pinch to zoom. F fits the board to the screen. With
        items selected: V {exploreEnabled ? 'explore' : 'vary'}, I inspect (or double-click), X mark not this, Delete remove, Command Z undo a move or a dismissed option. Explore axes run to the right of their source: each option is a card; open one to visualize, keep or regenerate it. With an image selected, its attribute chips below it explore that attribute.
      </p>
      {size.width > 0 && (
        <Stage
          ref={stageRef}
          width={size.width}
          height={size.height}
          x={view.x}
          y={view.y}
          scaleX={view.scale}
          scaleY={view.scale}
          draggable={spaceDown}
          onWheel={onWheel}
          onDragMove={onStageDrag}
          onDragEnd={onStageDrag}
          onMouseDown={onStageDown}
          onMouseMove={onStageMove}
          onTouchMove={onTouchMove}
          onTouchEnd={() => (pinch.current = null)}
        >
          <Layer>
            {noteLineage.map((l) => (
              <Line
                key={l.id}
                name="note-lineage"
                points={l.points}
                bezier
                stroke={palette.noteEdge}
                strokeWidth={1.3 / view.scale}
                listening={false}
              />
            ))}
            {lineage.map((l) => (
              <Line
                key={l.id}
                points={l.points}
                bezier
                stroke={palette.accent}
                strokeWidth={1.25 / view.scale}
                dash={[6 / view.scale, 4 / view.scale]}
                listening={false}
              />
            ))}
            {ordered.map((i) => (
              <ItemNode
                key={i.id}
                item={positioned(i)}
                scale={view.scale}
                draggable={!spaceDown && !(i.kind === 'note' && readOnly)}
                palette={palette}
                handlers={handlers}
                hidden={i.id === editing?.id}
              />
            ))}
            {ordered
              .filter((i) => i.kind === 'note')
              .map((n) => (
                <NoteVisualizing
                  key={`viz-${n.id}`}
                  note={positioned(n)}
                  siblings={noteChildren(n.id)}
                  scale={view.scale}
                  palette={palette}
                  reduced={reduced}
                />
              ))}
          </Layer>
          <Layer listening={false}>
            {ordered.map((i) => {
              const it = positioned(i)
              return (
                <ItemDecorations
                  key={i.id}
                  item={it}
                  bounds={itemBounds(it)}
                  scale={view.scale}
                  // the note being typed in: nothing drawn over its editor
                  hovered={hovered === i.id && i.id !== editing?.id}
                  selected={selected.includes(i.id) && i.id !== editing?.id}
                  reduced={reduced}
                  palette={palette}
                  verdictTone={itemVerdict(it, explorations, labels)?.tone}
                />
              )
            })}
            {marquee && (
              <Rect
                {...normalizeRect(marquee.a, marquee.b)}
                stroke={palette.accent}
                strokeWidth={1 / view.scale}
                dash={[4 / view.scale, 3 / view.scale]}
                fill={palette.accent}
                opacity={0.12}
              />
            )}
          </Layer>
        </Stage>
      )}

      {shownExplorations.length > 0 && (
        <AxisLayer
          items={axisItems}
          explorations={shownExplorations}
          selectedId={soleSelected?.id ?? null}
          view={view}
          locked={readOnly}
          onWheel={onOverlayWheel}
        />
      )}
      {hoveredItem && hoveredItem.kind !== 'link' && hoveredItem.parse_status !== 'completed' && (
        <StatusTip item={positioned(hoveredItem)} view={view} />
      )}
      {!dragging &&
        !marquee &&
        creditTargets(hoveredItem && positioned(hoveredItem), selectedItems).map((i) => (
          <CreditCaption
            key={`credit-${i.id}`}
            item={i}
            screen={toScreenBounds(itemBounds(i), view)}
            verdict={itemVerdict(i, explorations, labels)}
          />
        ))}
      {selBounds && !dragging && !marquee && !onlyNotes && (
        <ItemToolbar
          items={selectedItems}
          screen={toScreenBounds(selBounds, view)}
          onExplore={() => selectedItems[0] && onOpenPanel(exploreEnabled ? 'explore' : 'vary', selectedItems[0].id)}
          onInspect={() => selectedItems[0] && onOpenPanel('inspect', selectedItems[0].id)}
          onCompare={() =>
            selectedItems[0] && onOpenPanel('compare', selectedItems[0].id, { itemIds: selectedItems.map((i) => i.id) })
          }
          onNotThis={() => actions.toggleNotThis(selectedItems)}
          onRemove={() => actions.remove(selected)}
          readOnly={readOnly}
          explore={exploreEnabled}
        />
      )}
      {exploreEnabled && soleSelected && !dragging && !marquee && tool !== 'axis' && (
        <ItemChips
          key={soleSelected.id}
          item={soleSelected}
          screen={toScreenBounds(itemBounds(soleSelected), view)}
          locked={readOnly}
        />
      )}
      {exploreEnabled && tool === 'axis' && soleSelected?.kind === 'image' && !dragging && !readOnly && (
        <AxisPicker
          key={soleSelected.id}
          item={soleSelected}
          screen={toScreenBounds(itemBounds(soleSelected), view)}
          onDone={() => setTool('select')}
        />
      )}
      {stripItem && !dragging && (
        <FramesStrip
          itemId={stripItem.id}
          screen={toScreenBounds(itemBounds(positioned(stripItem)), view)}
          onChoose={(frameId) => void actions.chooseFrame(stripItem.id, frameId)}
          readOnly={readOnly}
          onEnter={() => {
            overStrip.current = true
            clearTimeout(stripTimer.current)
          }}
          onLeave={() => {
            overStrip.current = false
            setStripFor(null)
          }}
        />
      )}
      {barNote && !dragging && !marquee && (
        <NoteBar
          key={barNote.id}
          boardId={boardId}
          note={barNote}
          screen={toScreenBounds(itemBounds(positioned(barNote)), view)}
          readOnly={readOnly}
          onVisualize={() => actions.visualizeNote(barNote.id)}
          onEdit={() => setEditing({ id: barNote.id })}
          onDelete={() => actions.deleteNote(barNote)}
          onSendToNode={onSendToNode}
          onEnter={() => {
            overNoteBar.current = true
            clearTimeout(noteHoverTimer.current)
          }}
          onLeave={() => {
            overNoteBar.current = false
            noteHoverTimer.current = setTimeout(() => setNoteHover(null), 250)
          }}
        />
      )}
      {editing && editorAt && (
        <NoteEditor
          key={editing.id ?? 'new'}
          screen={toScreenBounds({ x: editorAt.x, y: editorAt.y, width: NOTE_W, height: NOTE_MIN_H }, view)}
          scale={view.scale}
          initial={editorAt.text}
          onCommit={commitNote}
        />
      )}
      {tool === 'note' && !readOnly && !editing && (
        <button type="button" className="sr-only" onClick={addNoteAtCenter}>
          Add a note in the middle of the view
        </button>
      )}
      {dropActive && <div className="drop-hint">Drop to add here</div>}
      <ItemList items={ordered} selected={selected} />
    </div>
  )
}

function StatusTip({ item, view }: { item: Item; view: View }) {
  const b: Bounds = toScreenBounds(itemBounds(item), view)
  return (
    <div className="status-tip" role="status" style={{ left: b.x - 20, top: b.y - 9 }}>
      {statusLabel(item)}
    </div>
  )
}

/** Keyboard and screen-reader access to the items drawn on the canvas. */
function ItemList({ items, selected }: { items: Item[]; selected: readonly string[] }) {
  return (
    <ul className="sr-only" aria-label="Items on this board">
      {items.map((i) => (
        <li key={i.id}>
          <button
            type="button"
            aria-pressed={selected.includes(i.id)}
            onClick={(e) => (e.shiftKey ? selection.toggle(i.id) : selection.select([i.id]))}
          >
            {i.kind === 'note'
              ? `note ${i.note_text ?? ''}`
              : `${i.kind} ${i.original_filename ?? i.page_title ?? i.page_url ?? i.id} · ${statusLabel(i)}`}
            {i.role === 'counter_example' ? ' · not this' : ''}
          </button>
        </li>
      ))}
    </ul>
  )
}
