import type Konva from 'konva'
import {
  type DragEvent as ReactDragEvent,
  type ReactNode,
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
import { useQueryClient } from '@tanstack/react-query'
import { Group, Layer, Line, Rect, Stage } from 'react-konva'
import { type Exploration, exploreItem, isGenerated, type Item, keys, type PartView, type Point, type Region, type UploadOrigin } from '../api'
import { useDemo } from '../demo'
import { withExploration } from '../explore/logic'
import { itemVerdict } from '../explore/verdict'
import { Edges } from '../living/Edges'
import { useKonvaBodies } from '../living/useKonvaBodies'
import { useLiveBoxes } from '../living/useLiveBounds'
import { LivingProvider } from '../living/useLiving'
import { useLivingScene } from '../living/useLivingScene'
import { createLivingWorld, type LivingWorld } from '../living/world'
import { Callouts } from '../map/Callouts'
import { setCollapsed } from '../map/collapse'
import { FlowerLayer } from '../map/Flower'
import { RegionOverlay } from '../map/RegionOverlay'
import { useNodeDrop } from '../plugins/nodeDrop'
import { NodeLayer } from '../plugins/NodeLayer'
import { useAnalysis, useBoardLens, useExplorations, useRegion, visibleItems } from '../queries'
import { setTool, useTool } from '../shell/tools'
import type { ItemActions } from './actions'
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
  onOpenPanel: (kind: 'inspect' | 'compare', itemId: string, params?: Record<string, unknown>) => void
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

const centreOf = (b: Bounds): Point => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 })

/** Where an item is now in the living world (its stored bounds until it has a body). */
function liveBounds(world: LivingWorld, item: Item): Bounds {
  const b = world.body(item.id)
  return b ? { x: b.x - b.w / 2, y: b.y - b.h / 2, width: b.w, height: b.h } : itemBounds(item)
}

const sameCounts = (a: Record<string, number>, b: Record<string, number>) =>
  Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => b[k] === v)

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
  const qc = useQueryClient()
  const [hoveredPart, setHoveredPart] = useState<{ itemId: string; part: string } | null>(null)
  // staged takes wait in their option's stage; notes are drawn at the size their text needs
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
  const [dragging, setDragging] = useState(false)
  // the open add-forms on the selected item's callout cards (they make its card bodies taller)
  const [forms, setForms] = useState<Record<string, number>>({})
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])
  // every board item is drawn where its body is, docked takes included
  const items = visible
  /** The dragged node's position at drag start, and every item it carries. */
  const dragStart = useRef<{ at: Point; ids: string[] } | null>(null)
  const [marquee, setMarquee] = useState<{ a: Point; b: Point; additive: boolean } | null>(null)
  const [dropActive, setDropActive] = useState(false)
  const pinch = useRef<{ dist: number; center: Point } | null>(null)
  const { selected } = useSelection()
  const palette = useCanvasPalette()
  const reduced = usePrefersReducedMotion()
  const fitted = useRef(false)
  const viewport = useMemo(
    () => ({ x: -view.x / view.scale, y: -view.y / view.scale, width: size.width / view.scale, height: size.height / view.scale }),
    [view, size],
  )
  const nodeDrop = useNodeDrop(boardId, readOnly)
  // the living board: one world per board, its loop running while the canvas is up
  const [living, setLiving] = useState(() => ({ boardId, world: createLivingWorld({ reduced }) }))
  if (living.boardId !== boardId) setLiving({ boardId, world: createLivingWorld({ reduced }) })
  const world = living.world
  useLayoutEffect(() => world.setReduced(reduced), [world, reduced])
  useEffect(() => {
    world.start()
    return () => world.stop()
  }, [world])
  useEffect(() => {
    if (viewport.width > 0) world.setViewport(viewport) // unmeasured, nothing sleeps
  }, [world, viewport])
  const itemLayer = useRef<Konva.Layer>(null)
  const decorLayer = useRef<Konva.Layer>(null)
  useKonvaBodies(world, itemLayer)
  useKonvaBodies(world, decorLayer)

  const byId = useMemo(() => new Map(visible.map((i) => [i.id, i])), [visible])
  const listed = useMemo(
    () => [...visible].sort((a, b) => a.z - b.z || a.created_at.localeCompare(b.created_at)),
    [visible],
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
  // over the flowers and callouts (HTML above the stage) the wheel still pans and zooms the canvas
  const onOverlayWheel = (e: ReactWheelEvent) => {
    if (!container || (e.target as HTMLElement).closest('.petal-card')) return
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
    const hits = tiny ? [] : visible.filter((i) => rectsIntersect(r, liveBounds(world, i))).map((i) => i.id)
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
    // Konva moves the dragged node; the world carries every picked body (and pushes the others)
    onDragStart: (e, item) => {
      e.cancelBubble = true
      const picked = (selected.includes(item.id) ? selected : [item.id]).filter((id) => byId.has(id))
      if (!selected.includes(item.id)) selection.select([item.id])
      dragStart.current = { at: e.target.position(), ids: picked }
      world.grab(picked)
      setDragging(true)
    },
    onDragMove: (e) => {
      e.cancelBubble = true
      const s = dragStart.current
      if (!s) return
      world.dragBy(e.target.x() - s.at.x, e.target.y() - s.at.y)
      nodeDrop.hover(pointerCanvas())
    },
    onDragEnd: (e, item) => {
      e.cancelBubble = true
      const s = dragStart.current
      dragStart.current = null
      if (!s) return
      setDragging(false)
      const centres = world.release()
      // released over a plugin node: the items become its inputs and go back where they were
      if (nodeDrop.drop(pointerCanvas(), selected.includes(item.id) ? selected : [item.id])) {
        for (const id of s.ids) {
          const it = byId.get(id)
          if (it) world.place(id, centreOf(itemBounds(it)))
        }
        return
      }
      const moves: Move[] = s.ids.flatMap((id) => {
        const it = byId.get(id)
        const c = centres.get(id)
        if (!it || !c) return []
        const b = itemBounds(it)
        return [{ id, from: { x: it.x, y: it.y }, to: { x: Math.round(c.x - b.width / 2), y: Math.round(c.y - b.height / 2) } }]
      })
      actions.move(moves)
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
    return it ? [it] : []
  })
  const stripItem = stripFor ? byId.get(stripFor) : undefined
  const hoveredItem = hovered ? byId.get(hovered) : undefined
  // an image made from a note always shows the solid line back to it (its provenance)
  const fromNote = (child: Item) => isGenerated(child) && byId.get(child.parent_item_id ?? '')?.kind === 'note'
  const noteLineage = items.flatMap((child) => {
    if (!fromNote(child)) return []
    const parent = byId.get(child.parent_item_id!)!
    return [{ id: child.id, parent: parent.id, points: lineagePoints(itemBounds(parent), itemBounds(child)) }]
  })
  const noteChildren = (noteId: string) => items.filter((i) => i.parent_item_id === noteId && isGenerated(i))
  const lineage = visible.flatMap((child) => {
    const parent = child.parent_item_id ? byId.get(child.parent_item_id) : undefined
    if (!parent || fromNote(child) || !(selected.includes(child.id) || selected.includes(parent.id))) return []
    return [{ id: child.id, parent: parent.id, points: lineagePoints(itemBounds(parent), itemBounds(child)) }]
  })
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
  // ---- the selected item's part callouts and the hovered part's region ----
  // not on a link
  const calloutItem =
    soleSelected &&
    soleSelected.kind !== 'link' &&
    !dragging &&
    !marquee &&
    soleSelected.id !== editing?.id
      ? soleSelected
      : undefined
  const analysis = useAnalysis(calloutItem?.id ?? null).data
  // a note still being read (or that could not be) shows nothing until it has parts or dimensions
  const showCallouts =
    !!analysis && (analysis.parse_status === 'completed' || analysis.parts.length > 0 || analysis.dimensions.length > 0)
  const scene = useLivingScene(boardId, visible, calloutItem && showCallouts ? calloutItem.id : null, forms)
  const onForms = useCallback((next: Record<string, number>) => setForms((cur) => (sameCounts(cur, next) ? cur : next)), [])
  useLayoutEffect(() => world.sync(scene), [world, scene])
  useLayoutEffect(() => world.setPinned(selected), [world, selected])
  // a selected item is pinned: when its stored spot changes (an undo, a move elsewhere) it goes there at once
  const storedAt = useRef(new Map<string, Point>())
  useLayoutEffect(() => {
    const next = new Map(visible.map((i) => [i.id, centreOf(itemBounds(i))]))
    for (const id of selected) {
      const was = storedAt.current.get(id)
      const now = next.get(id)
      if (was && now && (was.x !== now.x || was.y !== now.y) && world.body(id)?.kind === 'item') world.place(id, now)
    }
    storedAt.current = next
  }, [world, visible, selected])
  const hoveredPartView =
    calloutItem && hoveredPart?.itemId === calloutItem.id ? analysis?.parts.find((p) => p.key === hoveredPart.part) : undefined
  const regionQuery = useRegion(calloutItem?.id ?? '', hoveredPartView?.key ?? '', !!hoveredPartView)
  const hoveredRegion = regionOf(hoveredPartView, regionQuery.data, regionQuery.isPending)
  const noteHighlight =
    calloutItem?.kind === 'note' && hoveredRegion?.region.kind === 'text_range' && hoveredRegion.region.range?.length === 2
      ? (hoveredRegion.region.range as [number, number])
      : null
  // a dimension clicked on a callout: open its flower when it has one, else ask for options first (notes, no media)
  const openDimension = async (item: Item, key: string) => {
    const live = explorations?.find((e) => e.item_id === item.id && e.key === key)
    if (live) {
      setCollapsed(boardId, live.id, false)
      // out of sight: bring its hub into view
      const hub = world.body(`hub:${live.id}`)
      const v = viewport
      const b = hub && { x: hub.x - hub.w / 2, y: hub.y - hub.h / 2, width: hub.w, height: hub.h }
      if (b && !(b.x >= v.x && b.y >= v.y && b.x + b.width <= v.x + v.width && b.y + b.height <= v.y + v.height)) {
        setView((cur) => centeredView(cur, b, size))
      }
      return
    }
    const e = await exploreItem(item.id, { key, mode: 'initial' })
    qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withExploration(old, e))
    setCollapsed(boardId, e.id, false)
  }
  const addNoteAtCenter = () => {
    const c = toCanvasPoint({ x: size.width / 2, y: size.height / 2 }, viewRef.current)
    setTool('select')
    setEditing({ id: null, at: { x: c.x - NOTE_W / 2, y: c.y - NOTE_MIN_H / 2 } })
  }

  const gridStep = GRID * view.scale * (view.scale < 0.5 ? 4 : view.scale < 1 ? 2 : 1)

  return (
    <LivingProvider world={world}>
      <div
        ref={setContainer}
        className={`canvas${dropActive ? ' is-drop' : ''}${spaceDown ? ' is-pan' : ''}${tool === 'note' && !readOnly ? ' is-note' : ''}`}
        style={{
          backgroundSize: `${gridStep}px ${gridStep}px`,
          backgroundPosition: `${view.x}px ${view.y}px`,
        }}
        role="region"
        aria-label={`Board canvas, ${visible.length} ${visible.length === 1 ? 'item' : 'items'}, zoom ${Math.round(view.scale * 100)}%`}
        aria-describedby="canvas-help"
        onDragOver={onDragOver}
        onDragLeave={() => setDropActive(false)}
        onDrop={onDrop}
      >
        <p id="canvas-help" className="sr-only">
          Space and drag or two-finger scroll to pan; control and scroll or pinch to zoom. F fits the board to the screen. With
          items selected: I inspect (or double-click), X mark not this, Delete remove, Command Z undo a move or a dismissed option. A
          selected item shows its parts as callouts around it: hover one to see its region, click a dimension to open its flower:
          its options sit around a hub as petals; open one to render, keep or drop it. The hub's minus button collapses a flower.
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
            <Layer ref={itemLayer}>
              {noteLineage.map((l) => (
                <Line
                  key={l.id}
                  name="note-lineage"
                  link={[l.parent, l.id]}
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
                  link={[l.parent, l.id]}
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
                  item={i}
                  scale={view.scale}
                  draggable={!spaceDown && !(i.kind === 'note' && readOnly)}
                  palette={palette}
                  handlers={handlers}
                  hidden={i.id === editing?.id}
                  highlight={i.id === calloutItem?.id ? noteHighlight : null}
                />
              ))}
              {ordered
                .filter((i) => i.kind === 'note')
                .map((n) => (
                  <NoteVisualizing
                    key={`viz-${n.id}`}
                    note={n}
                    siblings={noteChildren(n.id)}
                    scale={view.scale}
                    palette={palette}
                    reduced={reduced}
                  />
                ))}
            </Layer>
            <Layer ref={decorLayer} listening={false}>
              {ordered.map((i) => {
                // drawn in the item's own frame, which follows its body
                const b = itemBounds(i)
                return (
                  <Group key={i.id} name="item-decor" body={i.id} x={b.x} y={b.y}>
                    <ItemDecorations
                      item={i}
                      bounds={{ x: 0, y: 0, width: b.width, height: b.height }}
                      scale={view.scale}
                      // the note being typed in: nothing drawn over its editor
                      hovered={hovered === i.id && i.id !== editing?.id}
                      selected={selected.includes(i.id) && i.id !== editing?.id}
                      reduced={reduced}
                      palette={palette}
                      verdictTone={itemVerdict(i, explorations, labels)?.tone}
                    />
                  </Group>
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

        <Edges scene={scene} view={view} />
        {exploreEnabled && (
          <FlowerLayer boardId={boardId} items={visible} view={view} flowers={scene.flowers} locked={readOnly} onWheel={onOverlayWheel} />
        )}
        <NodeLayer boardId={boardId} items={visible} view={view} size={size} readOnly={readOnly} onWheel={onOverlayWheel} />
        {hoveredItem && hoveredItem.kind !== 'link' && hoveredItem.kind !== 'note' && hoveredItem.parse_status !== 'completed' && (
          <Live items={[hoveredItem]}>{(b) => <StatusTip item={hoveredItem} screen={toScreenBounds(b, view)} />}</Live>
        )}
        {!dragging &&
          !marquee &&
          creditTargets(hoveredItem, selectedItems).map((i) => (
            <Live key={`credit-${i.id}`} items={[i]}>
              {(b) => <CreditCaption item={i} screen={toScreenBounds(b, view)} verdict={itemVerdict(i, explorations, labels)} />}
            </Live>
          ))}
        {selectedItems.length > 0 && !dragging && !marquee && !onlyNotes && (
          <Live items={selectedItems}>
            {(b) => (
              <ItemToolbar
                items={selectedItems}
                screen={toScreenBounds(b, view)}
                onInspect={() => selectedItems[0] && onOpenPanel('inspect', selectedItems[0].id)}
                onCompare={() =>
                  selectedItems[0] && onOpenPanel('compare', selectedItems[0].id, { itemIds: selectedItems.map((i) => i.id) })
                }
                onNotThis={() => actions.toggleNotThis(selectedItems)}
                onRemove={() => actions.remove(selected)}
                onReanalyse={actions.reanalyse}
                readOnly={readOnly}
              />
            )}
          </Live>
        )}
        {calloutItem && hoveredRegion && (
          <Live items={[calloutItem]}>
            {(b) => (
              <RegionOverlay item={{ ...calloutItem, x: b.x, y: b.y }} region={hoveredRegion.region} loading={hoveredRegion.loading} view={view} />
            )}
          </Live>
        )}
        {calloutItem && analysis && showCallouts && (
          <Callouts
            key={`callouts-${calloutItem.id}`}
            item={calloutItem}
            analysis={analysis}
            view={view}
            onForms={onForms}
            locked={readOnly}
            onOpenDimension={exploreEnabled ? (key) => openDimension(calloutItem, key) : undefined}
            onHoverPart={(part) => setHoveredPart(part ? { itemId: calloutItem.id, part } : null)}
            onWheel={onOverlayWheel}
          />
        )}
        {stripItem && !dragging && (
          <Live items={[stripItem]}>
            {(b) => (
              <FramesStrip
                itemId={stripItem.id}
                screen={toScreenBounds(b, view)}
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
          </Live>
        )}
        {barNote && !dragging && !marquee && (
          <Live key={`note-bar-${barNote.id}`} items={[barNote]}>
            {(b) => (
              <NoteBar
                boardId={boardId}
                note={barNote}
                screen={toScreenBounds(b, view)}
                readOnly={readOnly}
                onVisualize={() => actions.visualizeNote(barNote.id)}
                onEdit={() => setEditing({ id: barNote.id })}
                onDelete={() => actions.deleteNote(barNote)}
                onReanalyse={actions.reanalyse}
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
          </Live>
        )}
        {editing && editorAt && (
          // an existing note's editor sits where the note is now
          <Live key={editing.id ?? 'new'} items={editedNote ? [editedNote] : []}>
            {(b) => (
              <NoteEditor
                screen={toScreenBounds(
                  { x: editedNote ? b.x : editorAt.x, y: editedNote ? b.y : editorAt.y, width: NOTE_W, height: NOTE_MIN_H },
                  view,
                )}
                scale={view.scale}
                initial={editorAt.text}
                onCommit={commitNote}
              />
            )}
          </Live>
        )}
        {tool === 'note' && !readOnly && !editing && (
          <button type="button" className="sr-only" onClick={addNoteAtCenter}>
            Add a note in the middle of the view
          </button>
        )}
        {dropActive && <div className="drop-hint">Drop to add here</div>}
        <ItemList items={listed} selected={selected} />
      </div>
    </LivingProvider>
  )
}

/**
 * Renders `children` with where `items` are now (the union of their live bounds; their stored bounds
 * until they have bodies), re-rendering as they float without re-rendering the canvas.
 */
function Live({ items, children }: { items: readonly Item[]; children: (b: Bounds) => ReactNode }) {
  const live = useLiveBoxes(items.map((i) => i.id))
  const b = unionBounds(live ?? items.map(itemBounds))
  return <>{children(b ?? { x: 0, y: 0, width: 0, height: 0 })}</>
}

function StatusTip({ item, screen: b }: { item: Item; screen: Bounds }) {
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

/**
 * What to draw for a hovered part: its region once known; until then the stored region (a box or a
 * passage is already exact) or, for a mask being found, a loading outline of its bbox. A mask that
 * could not be found falls back to an outline of its bbox (or of the whole item).
 */
function regionOf(part: PartView | undefined, fetched: Region | undefined, pending: boolean): { region: Region; loading: boolean } | null {
  if (!part) return null
  if (fetched) return { region: fetched, loading: false }
  const r = part.region ?? undefined
  if (part.region_kind === 'box') return r ? { region: { kind: 'box', box: r }, loading: false } : null
  if (part.region_kind === 'text_range') return r ? { region: { kind: 'text_range', range: r }, loading: false } : null
  return { region: { kind: 'mask', box: r }, loading: pending }
}
