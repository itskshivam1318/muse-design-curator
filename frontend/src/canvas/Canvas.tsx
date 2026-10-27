import type Konva from 'konva'
import {
  type DragEvent as ReactDragEvent,
  type Ref,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Layer, Line, Rect, Stage } from 'react-konva'
import type { Exploration, Item, Point, UploadOrigin } from '../api'
import { useDemo } from '../demo'
import { useExplorations } from '../queries'
import type { ItemActions } from './actions'
import { handleDrop } from './drop'
import { FramesStrip } from './FramesStrip'
import {
  type Bounds,
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
import { ItemDecorations, type ItemHandlers, ItemNode } from './ItemNode'
import { CreditCaption } from './CreditCaption'
import { creditTargets } from './credit'
import { ItemToolbar } from './ItemToolbar'
import { itemBounds, lineagePoints, statusLabel } from './nodeProps'
import { noteLines, placedNotes, type PlacedNote } from './notes'
import { OptionNote } from './OptionNote'
import { useCanvasPalette, usePrefersReducedMotion } from './palette'
import { selection, useSelection } from './selection'

export interface CanvasHandle {
  fit: () => void
  /** The canvas point at the centre of the viewport (where pastes and menu uploads land). */
  center: () => Point
  /** Where an item's bounds sit on the page (client coordinates), e.g. for the Keep fly-in. */
  clientRectOf: (item: Item) => Bounds | null
}

interface Props {
  boardId: string
  items: Item[]
  actions: ItemActions
  onFiles: (files: File[], at: Point, origin: UploadOrigin) => void
  onOpenPanel: (kind: 'explore' | 'vary' | 'inspect' | 'compare', itemId: string, params?: Record<string, unknown>) => void
  spaceDown: boolean
  ref?: Ref<CanvasHandle>
  /** Public demo, not unlocked: no file drops, role changes, removal or frame choice. */
  readOnly?: boolean
}

type KEvent<E extends Event = MouseEvent> = Konva.KonvaEventObject<E>

const GRID = 24

/** Keep fitted items clear of the context bar (top-left), signals (right) and + button (bottom). */
function fitInsets(width: number) {
  return width > 900 ? { top: 140, right: 310, bottom: 96, left: 72 } : { top: 140, right: 24, bottom: 96, left: 24 }
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

export function Canvas({ boardId, items, actions, onFiles, onOpenPanel, spaceDown, ref, readOnly = false }: Props) {
  const { exploreEnabled } = useDemo()
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
  // a note being dragged: its lines follow the pointer until the drop saves the spot
  const [noteDrag, setNoteDrag] = useState<({ id: string } & Point) | null>(null)
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
    setView(fitView(items.map(itemBounds), size, fitInsets(size.width)))
  }, [items, size])

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
    }),
    [fit, size, container],
  )

  // ---- pan & zoom ----
  const onWheel = (e: KEvent<WheelEvent>) => {
    e.evt.preventDefault()
    const stage = stageRef.current
    const pointer = stage?.getPointerPosition() ?? { x: size.width / 2, y: size.height / 2 }
    if (e.evt.ctrlKey || e.evt.metaKey) {
      // ctrl+wheel, or a trackpad pinch (browsers report pinches as ctrl+wheel)
      setView((v) => zoomAt(v, pointer, v.scale * wheelZoomFactor(e.evt.deltaY)))
    } else {
      // two-finger scroll pans
      setView((v) => ({ ...v, x: v.x - e.evt.deltaX, y: v.y - e.evt.deltaY }))
    }
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
      const ids = selected.includes(item.id) ? selected : [item.id]
      if (!selected.includes(item.id)) selection.select([item.id])
      dragStart.current = new Map(
        ids.flatMap((id) => {
          const it = byId.get(id)
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
      if (item.kind !== 'link') onOpenPanel('inspect', item.id)
    },
    onEnter: (item) => {
      setHovered(item.id)
      if (item.kind === 'video') {
        clearTimeout(stripTimer.current)
        setStripFor(item.id)
      }
    },
    onLeave: (item) => {
      setHovered((h) => (h === item.id ? null : h))
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
  const lineage = items.flatMap((child) => {
    const parent = child.parent_item_id ? byId.get(child.parent_item_id) : undefined
    if (!parent || !(selected.includes(child.id) || selected.includes(parent.id))) return []
    return [{ id: child.id, points: lineagePoints(itemBounds(positioned(parent)), itemBounds(positioned(child))) }]
  })
  const shownItems = ordered.map(positioned)
  const notes = placedNotes(explorations ?? [], shownItems)
  const noteLinks = noteLines(withDraggedNote(explorations ?? [], noteDrag), shownItems)
  const openNote = (n: PlacedNote) =>
    onOpenPanel('explore', n.exploration.item_id, { key: n.exploration.key, optionId: n.option.id })
  const gridStep = GRID * view.scale * (view.scale < 0.5 ? 4 : view.scale < 1 ? 2 : 1)

  return (
    <div
      ref={setContainer}
      className={`canvas${dropActive ? ' is-drop' : ''}${spaceDown ? ' is-pan' : ''}`}
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
        items selected: V {exploreEnabled ? 'explore' : 'vary'}, I inspect (or double-click), X mark not this, Delete remove, Command Z undo a move or a dismissed option. Explore notes sit beside their source and are listed after the items.
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
            {noteLinks.map((l) => (
              <Line
                key={l.id}
                points={l.points}
                bezier
                stroke={palette.noteEdge}
                strokeWidth={1.25 / view.scale}
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
                draggable={!spaceDown}
                palette={palette}
                handlers={handlers}
              />
            ))}
            {notes.map((n) => (
              <OptionNote
                key={n.option.id}
                option={n.option}
                x={n.x}
                y={n.y}
                scale={view.scale}
                palette={palette}
                editable={!readOnly}
                panning={spaceDown}
                onOpen={() => openNote(n)}
                onDragMove={(o, at) => setNoteDrag({ id: o.id, ...at })}
                onMove={(o, from, to) => {
                  setNoteDrag(null)
                  if (from.x !== to.x || from.y !== to.y) actions.moveOption(o.id, from, to)
                }}
                onDismiss={(o) => actions.dismissOption(o)}
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
                  hovered={hovered === i.id}
                  selected={selected.includes(i.id)}
                  reduced={reduced}
                  palette={palette}
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

      {hoveredItem && hoveredItem.kind !== 'link' && hoveredItem.parse_status !== 'completed' && (
        <StatusTip item={positioned(hoveredItem)} view={view} />
      )}
      {!dragging &&
        !marquee &&
        creditTargets(hoveredItem && positioned(hoveredItem), selectedItems).map((i) => (
          <CreditCaption key={`credit-${i.id}`} item={i} screen={toScreenBounds(itemBounds(i), view)} />
        ))}
      {selBounds && !dragging && !marquee && (
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
      {dropActive && <div className="drop-hint">Drop to add here</div>}
      <ItemList items={ordered} selected={selected} />
      <NoteList notes={notes} onOpen={openNote} />
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

/** The board's explorations as the canvas draws them while one note is dragged. */
function withDraggedNote(list: Exploration[], drag: ({ id: string } & Point) | null): Exploration[] {
  if (!drag) return list
  return list.map((e) => ({
    ...e,
    options: e.options.map((o) => (o.id === drag.id ? { ...o, x: drag.x, y: drag.y } : o)),
  }))
}

/** Keyboard and screen-reader access to the explore notes (one entry per note drawn). */
function NoteList({ notes, onOpen }: { notes: PlacedNote[]; onOpen: (n: PlacedNote) => void }) {
  if (notes.length === 0) return null
  return (
    <ul className="sr-only" aria-label="Explore notes on this board">
      {notes.map((n) => (
        <li key={n.option.id} data-testid="option-note" data-option-id={n.option.id}>
          <button type="button" onClick={() => onOpen(n)}>
            {n.option.name} · {n.option.distance}
          </button>
        </li>
      ))}
    </ul>
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
            {i.kind} {i.original_filename ?? i.page_title ?? i.page_url ?? i.id} · {statusLabel(i)}
            {i.role === 'counter_example' ? ' · not this' : ''}
          </button>
        </li>
      ))}
    </ul>
  )
}
