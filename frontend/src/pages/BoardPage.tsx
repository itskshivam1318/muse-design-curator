import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  type Board,
  confirmLens,
  type Item,
  itemImageUrl,
  keys,
  type LensSpec,
  patchBoard,
  type Point,
  type UploadOrigin,
} from '../api'
import { useItemActions } from '../canvas/actions'
import { Canvas, type CanvasHandle } from '../canvas/Canvas'
import type { Bounds } from '../canvas/geometry'
import { usePrefersReducedMotion } from '../canvas/palette'
import { handlePaste, readClipboard } from '../canvas/paste'
import { selection, selectionStore, useSelection } from '../canvas/selection'
import { useAddFlow } from '../canvas/useAddFlow'
import { useDemo } from '../demo'
import { connectBoardEvents } from '../events'
import { AddMenu } from '../panels/AddMenu'
import { BoardSignals } from '../panels/BoardSignals'
import { ContextBar, type ContextBarHandle } from '../panels/ContextBar'
import { DemoBadge } from '../panels/DemoBadge'
import { LensReview } from '../panels/LensReview'
import { Onboarding } from '../panels/Onboarding'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import { KeepFlight } from '../panels/KeepFlight'
import { MaybeStrip } from '../panels/MaybeStrip'
import '../panels/registerPanels'
import { RightDrawer } from '../panels/RightDrawer'
import { UploadStatus } from '../panels/UploadStatus'
import { useBoard, useBoardLens, useItems, useProfile } from '../queries'
import { Link } from '../Link'
import { insideOverlay } from './shortcutGuard'
import { runStore } from '../vary/runStore'

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el || !el.tagName) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

export function BoardPage({ boardId }: { boardId: string }) {
  const qc = useQueryClient()
  const board = useBoard(boardId)
  const items = useItems(boardId)
  const profile = useProfile(boardId)
  const lens = useBoardLens(boardId)
  const actions = useItemActions(boardId)
  const add = useAddFlow(boardId)
  const canvas = useRef<CanvasHandle>(null)
  const [addOpen, setAddOpen] = useState(false)
  const contextBar = useRef<ContextBarHandle>(null)
  const [dismissedLens, setDismissedLens] = useState<string | null>(null)
  const [spaceDown, setSpaceDown] = useState(false)
  const [live, setLive] = useState<'connecting' | 'open' | 'reconnecting'>('connecting')
  const { drawer } = useSelection()
  const reduced = usePrefersReducedMotion()
  const { locked, exploreEnabled } = useDemo()
  const [flight, setFlight] = useState<{ id: string; src: string; from: Bounds; to: Bounds } | null>(null)

  useEffect(() => {
    selection.reset()
    runStore.clear()
    return connectBoardEvents(boardId, qc, { onStatus: setLive })
  }, [boardId, qc])

  // Keep: the candidate flies from the popover onto the canvas next to its source, then is selected
  const onKept = useCallback(
    (item: Item, from: DOMRect | null) => {
      selection.select([item.id])
      const to = canvas.current?.clientRectOf(item)
      if (reduced || !from || !to) return
      setFlight({
        id: item.id,
        src: itemImageUrl(item, 'thumb'),
        from: { x: from.left, y: from.top, width: from.width, height: from.height },
        to,
      })
    },
    [reduced],
  )

  const center = useCallback((): Point => canvas.current?.center() ?? { x: 0, y: 0 }, [])
  const { addFiles, addLink } = add
  const uploadAt = useCallback(
    (files: File[], at: Point, origin: UploadOrigin) => addFiles(files, at, origin),
    [addFiles],
  )

  const openPanel = useCallback(
    (kind: 'explore' | 'vary' | 'inspect' | 'compare', itemId: string, params?: Record<string, unknown>) => {
      if (hasDrawerPanel(kind)) selection.openDrawer(kind, itemId, params)
    },
    [],
  )

  // ⌘V: images upload, URLs become link items, both at the viewport centre
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (locked || isTyping(e.target)) return
      const data = readClipboard(e.clipboardData)
      if (data.files.length === 0 && !data.text) return
      e.preventDefault()
      void handlePaste(data, { center: center(), uploadFiles: uploadAt, addLink }).catch(() => {})
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [addLink, center, uploadAt, locked])

  // keyboard shortcuts
  const itemsData = items.data
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      if (e.code === 'Space') {
        const tag = (e.target as HTMLElement | null)?.tagName
        if (tag === 'BUTTON' || tag === 'A') return // Space activates the focused control
        e.preventDefault()
        if (!e.repeat) setSpaceDown(true)
        return
      }
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        if (actions.undo()) e.preventDefault()
        return
      }
      if (mod || e.altKey) return
      if (e.key !== 'Escape' && insideOverlay(e.target)) return // not while a dialog or drawer has focus
      const sel = selectionStore.get().selected
      const chosen = (itemsData ?? []).filter((i) => sel.includes(i.id))
      switch (e.key.toLowerCase()) {
        case 'f':
          canvas.current?.fit()
          break
        case 'v':
          if (chosen.length === 1) openPanel(exploreEnabled ? 'explore' : 'vary', chosen[0].id)
          break
        case 'i':
          if (chosen.length === 1) openPanel('inspect', chosen[0].id)
          break
        case 'x':
          if (!locked) actions.toggleNotThis(chosen)
          break
        case 'delete':
        case 'backspace':
          if (chosen.length && !locked) {
            e.preventDefault()
            actions.remove(chosen.map((i) => i.id))
          }
          break
        case 'escape':
          // innermost first: candidate popover, then the drawer, then the selection
          if (runStore.get().openCandidate) runStore.open(null)
          else if (selectionStore.get().drawer) selection.closeDrawer()
          else selection.clear()
          setAddOpen(false)
          break
        default:
          return
      }
    }
    const onUp = (e: KeyboardEvent) => e.code === 'Space' && setSpaceDown(false)
    const onBlur = () => setSpaceDown(false)
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onUp)
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onUp)
      window.removeEventListener('blur', onBlur)
    }
  }, [actions, itemsData, openPanel, locked, exploreEnabled])

  const saveBoard = async (patch: Partial<Pick<Board, 'title' | 'context' | 'domain'>>) => {
    const next = await patchBoard(boardId, patch)
    qc.setQueryData(keys.board(boardId), next)
    if ('domain' in patch) void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
  }

  const onConfirmLens = async (spec?: LensSpec) => {
    const row = await confirmLens(boardId, spec)
    qc.setQueryData(keys.lens(boardId), row)
    void qc.invalidateQueries({ queryKey: keys.board(boardId) })
  }

  if (board.isError) {
    const notFound = board.error instanceof ApiError && board.error.status === 404
    return (
      <main className="page-message">
        <h1>{notFound ? 'Board not found' : 'Could not load this board'}</h1>
        <p className="muted">{notFound ? 'It may have been deleted.' : String(board.error?.message ?? '')}</p>
        <Link href="/">All boards</Link>
      </main>
    )
  }

  const list = items.data ?? []
  const proposed = lens.data && lens.data.status === 'proposed' && lens.data.id !== dismissedLens ? lens.data : null

  return (
    <main className="board">
      <h1 className="sr-only">{board.data?.title ?? 'Board'}</h1>
      <Canvas
        ref={canvas}
        items={list}
        actions={actions}
        onFiles={uploadAt}
        onOpenPanel={openPanel}
        spaceDown={spaceDown}
        readOnly={locked}
      />

      <div className="float top-left">
        <Link href="/" className="back-link" aria-label="All boards">
          ←
        </Link>
        {board.data && (
          <ContextBar
            key={board.data.id}
            board={board.data}
            profile={profile.data?.profile}
            onSave={saveBoard}
            ref={contextBar}
            locked={locked}
            badge={<DemoBadge />}
          />
        )}
      </div>

      {items.isSuccess && (
        <Onboarding
          itemCount={list.length}
          onFocusContext={() => contextBar.current?.focus()}
          onOpenAdd={() => setAddOpen(true)}
        />
      )}

      <div className="float right">
        {!drawer && <BoardSignals boardId={boardId} />}
        {proposed && (
          <LensReview key={proposed.id} lens={proposed} onConfirm={onConfirmLens} onDismiss={() => setDismissedLens(proposed.id)} locked={locked} />
        )}
      </div>
      <RightDrawer boardId={boardId} />
      <MaybeStrip boardId={boardId} streamOpen={live === 'open'} onKept={onKept} />
      {flight && <KeepFlight key={flight.id} src={flight.src} from={flight.from} to={flight.to} onDone={() => setFlight(null)} />}

      <div className="float bottom-left">
        <UploadStatus jobs={add.jobs} onDismiss={add.dismiss} onCancel={add.cancel} />
        {actions.error && (
          <p className="toast error" role="alert">
            {actions.error}{' '}
            <button type="button" className="btn-quiet small" onClick={actions.clearError}>
              Dismiss
            </button>
          </p>
        )}
        <AddMenu
          open={addOpen}
          onOpenChange={setAddOpen}
          onFiles={(files) => uploadAt(files, center(), 'upload')}
          onLink={(url) => addLink(url, center())}
          disabled={locked}
        />
      </div>

      {live === 'reconnecting' && (
        <p className="live-status" role="status">
          Reconnecting to live updates…
        </p>
      )}
    </main>
  )
}
