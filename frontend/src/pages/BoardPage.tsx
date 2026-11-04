import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { setBoard as setTelemetryBoard } from '../telemetry'
import {
  ApiError,
  type Board,
  type Item,
  keys,
  patchBoard,
  type Point,
  type UploadOrigin,
} from '../api'
import { useItemActions } from '../canvas/actions'
import { Canvas, type CanvasHandle } from '../canvas/Canvas'
import { handlePaste, readClipboard } from '../canvas/paste'
import { selection, selectionStore } from '../canvas/selection'
import { useAddFlow } from '../canvas/useAddFlow'
import { useDemo } from '../demo'
import { connectBoardEvents } from '../events'
import { AddActions } from '../panels/AddMenu'
import { AddFab } from '../panels/AddFab'
import { BoardSignals } from '../panels/BoardSignals'
import { ContextBar, type ContextBarHandle } from '../panels/ContextBar'
import { DemoBadge } from '../panels/DemoBadge'
import { Onboarding } from '../panels/Onboarding'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import '../panels/registerPanels'
import { UploadStatus } from '../panels/UploadStatus'
import { useBoard, useItems, useProfile } from '../queries'
import { Link } from '../Link'
import { BoardShell } from '../shell/BoardShell'
import { closeRail, openRail, railStore, setTool } from '../shell/tools'
import { sendNoteToNode } from '../plugins/nodeDrop'
import { insideOverlay, isTyping, itemShortcut } from './shortcutGuard'

export function BoardPage({ boardId }: { boardId: string }) {
  const qc = useQueryClient()
  const board = useBoard(boardId)
  const items = useItems(boardId)
  const profile = useProfile(boardId)
  const actions = useItemActions(boardId)
  const add = useAddFlow(boardId)
  const canvas = useRef<CanvasHandle>(null)
  const contextBar = useRef<ContextBarHandle>(null)
  const [spaceDown, setSpaceDown] = useState(false)
  const [live, setLive] = useState<'connecting' | 'open' | 'reconnecting'>('connecting')
  const { locked, pluginsEnabled } = useDemo()

  useEffect(() => {
    selection.reset()
    setTool('select')
    closeRail()
    setTelemetryBoard(boardId)
    const disconnect = connectBoardEvents(boardId, qc, { onStatus: setLive })
    return () => {
      disconnect()
      setTelemetryBoard(null)
    }
  }, [boardId, qc])

  const center = useCallback((): Point => canvas.current?.center() ?? { x: 0, y: 0 }, [])
  const { addFiles, addLink } = add
  const uploadAt = useCallback(
    (files: File[], at: Point, origin: UploadOrigin) => addFiles(files, at, origin),
    [addFiles],
  )

  const openPanel = useCallback(
    (kind: 'inspect' | 'compare', itemId: string, params?: Record<string, unknown>) => {
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
        case 'i':
        case 'x': {
          // image shortcuts: a selected note is left out
          const act = itemShortcut(e.key, chosen, { locked })
          if (act?.kind === 'panel') openPanel(act.panel, act.itemId)
          else if (act?.kind === 'notThis') actions.toggleNotThis(act.items)
          break
        }
        case 'delete':
        case 'backspace':
          if (chosen.length && !locked) {
            e.preventDefault()
            actions.remove(chosen.map((i) => i.id))
          }
          break
        case 'escape':
          // innermost first: the drawer, then a rail panel, then the selection
          // (the tool goes back to Select in BoardShell's own handler)
          if (selectionStore.get().drawer) selection.closeDrawer()
          else if (railStore.get().open) closeRail()
          else selection.clear()
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
  }, [actions, itemsData, openPanel, locked])

  const saveBoard = async (patch: Partial<Pick<Board, 'title' | 'context' | 'domain'>>) => {
    const next = await patchBoard(boardId, patch)
    qc.setQueryData(keys.board(boardId), next)
    if ('domain' in patch) void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
  }

  if (board.isError) {
    const notFound = board.error instanceof ApiError && board.error.status === 404
    return (
      <main className="page-message">
        <h1>{notFound ? 'Board not found' : 'Could not load this board'}</h1>
        <p className="muted">{notFound ? 'It may have been deleted.' : String(board.error?.message ?? '')}</p>
        <Link href="/boards">All boards</Link>
      </main>
    )
  }

  const list = items.data ?? []

  const focusItem = (item: Item) => {
    selection.select([item.id])
    canvas.current?.centerOn(item)
  }

  return (
    <main className="board">
      <h1 className="sr-only">{board.data?.title ?? 'Board'}</h1>
      <BoardShell
        boardId={boardId}
        items={list}
        plugins={pluginsEnabled}
        onFocusItem={focusItem}
        header={
          <>
            <Link href="/boards" className="back-link" aria-label="All boards">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                <path d="M10 3L5 8l5 5" />
              </svg>
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
          </>
        }
        canvas={
          <Canvas
            ref={canvas}
            boardId={boardId}
            items={list}
            actions={actions}
            onFiles={uploadAt}
            onOpenPanel={openPanel}
            spaceDown={spaceDown}
            readOnly={locked}
            onSendToNode={pluginsEnabled ? (pluginId, noteId) => void sendNoteToNode(qc, boardId, pluginId, noteId) : undefined}
          />
        }
        add={
          <AddFab
            onFiles={(files) => uploadAt(files, center(), 'upload')}
            onLink={(url) => addLink(url, center())}
            disabled={locked}
          />
        }
        library={
          <>
            <AddActions
              onFiles={(files) => uploadAt(files, center(), 'upload')}
              onLink={(url) => addLink(url, center())}
              disabled={locked}
            />
            <BoardSignals boardId={boardId} />
          </>
        }
        overlays={
          <>
            {items.isSuccess && (
              <Onboarding
                items={list}
                onFocusContext={() => contextBar.current?.focus()}
                onOpenAdd={() => openRail('library')}
              />
            )}
            <div className="float stage-status">
              <UploadStatus jobs={add.jobs} onDismiss={add.dismiss} onCancel={add.cancel} />
              {actions.error && (
                <p className="toast error" role="alert">
                  {actions.error}{' '}
                  <button type="button" className="btn-quiet small" onClick={actions.clearError}>
                    Dismiss
                  </button>
                </p>
              )}
            </div>
            {live === 'reconnecting' && (
              <p className="live-status" role="status">
                Reconnecting to live updates…
              </p>
            )}
          </>
        }
      />
    </main>
  )
}
