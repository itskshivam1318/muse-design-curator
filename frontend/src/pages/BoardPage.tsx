import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, type Board, confirmLens, keys, type LensSpec, patchBoard, type Point, type UploadOrigin } from '../api'
import { useItemActions } from '../canvas/actions'
import { Canvas, type CanvasHandle } from '../canvas/Canvas'
import { handlePaste, readClipboard } from '../canvas/paste'
import { selection, selectionStore } from '../canvas/selection'
import { useAddFlow } from '../canvas/useAddFlow'
import { connectBoardEvents } from '../events'
import { AddMenu } from '../panels/AddMenu'
import { BoardSignals } from '../panels/BoardSignals'
import { ContextBar, type ContextBarHandle } from '../panels/ContextBar'
import { LensReview } from '../panels/LensReview'
import { Onboarding } from '../panels/Onboarding'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import { RightDrawer } from '../panels/RightDrawer'
import { UploadStatus } from '../panels/UploadStatus'
import { useBoard, useBoardLens, useItems, useProfile } from '../queries'
import { Link } from '../Link'

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
  const [live, setLive] = useState<'open' | 'reconnecting'>('open')

  useEffect(() => {
    selection.reset()
    return connectBoardEvents(boardId, qc, { onStatus: setLive })
  }, [boardId, qc])

  const center = useCallback((): Point => canvas.current?.center() ?? { x: 0, y: 0 }, [])
  const uploadAt = useCallback(
    (files: File[], at: Point, origin: UploadOrigin) => add.addFiles(files, at, origin),
    [add],
  )

  const openPanel = useCallback((kind: 'vary' | 'inspect', itemId: string) => {
    if (hasDrawerPanel(kind)) selection.openDrawer(kind, itemId)
  }, [])

  // ⌘V: images upload, URLs become link items, both at the viewport centre
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (isTyping(e.target)) return
      const data = readClipboard(e.clipboardData)
      if (data.files.length === 0 && !data.text) return
      e.preventDefault()
      void handlePaste(data, { center: center(), uploadFiles: uploadAt, addLink: add.addLink }).catch(() => {})
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [add.addLink, center, uploadAt])

  // keyboard shortcuts
  const itemsData = items.data
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      if (e.code === 'Space') {
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
      const sel = selectionStore.get().selected
      const chosen = (itemsData ?? []).filter((i) => sel.includes(i.id))
      switch (e.key.toLowerCase()) {
        case 'f':
          canvas.current?.fit()
          break
        case 'v':
          if (chosen.length === 1) openPanel('vary', chosen[0].id)
          break
        case 'i':
          if (chosen.length === 1) openPanel('inspect', chosen[0].id)
          break
        case 'x':
          actions.toggleNotThis(chosen)
          break
        case 'delete':
        case 'backspace':
          if (chosen.length) {
            e.preventDefault()
            actions.remove(chosen.map((i) => i.id))
          }
          break
        case 'escape':
          selection.clear()
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
  }, [actions, itemsData, openPanel])

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
        <BoardSignals boardId={boardId} />
        {proposed && (
          <LensReview key={proposed.id} lens={proposed} onConfirm={onConfirmLens} onDismiss={() => setDismissedLens(proposed.id)} />
        )}
      </div>
      <RightDrawer boardId={boardId} />

      <div className="float bottom-left">
        <UploadStatus jobs={add.jobs} onDismiss={add.dismiss} />
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
          onLink={(url) => add.addLink(url, center())}
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
