import { type ReactNode, useEffect, useRef, useState } from 'react'
import type { Item } from '../api'
import { NodesMenu } from '../plugins/NodesMenu'
import { RightDrawer } from '../panels/RightDrawer'
import { toolShortcutAllowed } from '../pages/shortcutGuard'
import { AgentCard } from './AgentCard'
import { BottomToolbar } from './BottomToolbar'
import { LeftRail } from './LeftRail'
import { RailPanel } from './RailPanel'
import { closeRail as closeRailState, openRail, railStore, setTool, toolForKey, useRail } from './tools'
import './shell.css'

interface Props {
  boardId: string
  items: Item[]
  /** The header row: back link, title and context sentence. */
  header: ReactNode
  /** The canvas, filling the rounded stage. */
  canvas: ReactNode
  /** Library panel extras under the items list (add actions, board signals, lens review). */
  library?: ReactNode
  /** Floating things over the stage (onboarding, upload status, the maybe strip…). */
  overlays?: ReactNode
  onFocusItem: (item: Item) => void
  onFindExamples: (item: Item) => void
  /** Server flags: plugins on shows the Plugins rail icon and Nodes; explore on shows Axis. */
  plugins: boolean
  explore: boolean
}

/** The calm board: header, slim left rail with slide-outs, the canvas stage, tools and the agent card. */
export function BoardShell({ boardId, items, header, canvas, library, overlays, onFocusItem, onFindExamples, plugins, explore }: Props) {
  const railState = useRail()
  const rail = railState.open === 'plugins' && !plugins ? null : railState.open
  const [nodesOpen, setNodesOpen] = useState(false)
  const showNodes = nodesOpen && plugins
  const stage = useRef<HTMLElement>(null)
  // picked in Library: focus goes back to the board so its shortcuts work again
  const focusItem = (item: Item) => {
    onFocusItem(item)
    stage.current?.focus()
  }

  // tool shortcuts: n note, a axis, Escape select (never while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!toolShortcutAllowed(e)) return
      const t = toolForKey(e.key, { explore })
      if (t) setTool(t)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [explore])

  const closeRail = () => {
    const was = railStore.get().open
    closeRailState()
    if (was) document.querySelector<HTMLElement>(`.left-rail [data-rail="${was}"]`)?.focus()
  }

  return (
    <div className="board-shell">
      <header className="board-header">{header}</header>
      <div className="board-body">
        <LeftRail
          open={rail}
          onOpen={(id) => (id ? openRail(id) : closeRailState())}
          plugins={plugins}
          lensWaiting={railState.lensWaiting}
        />
        <section className="board-stage" aria-label="Canvas" tabIndex={-1} ref={stage}>
          {canvas}
          {overlays}
          {rail && (
            <RailPanel
              id={rail}
              boardId={boardId}
              items={items}
              onClose={closeRail}
              onFocusItem={focusItem}
              onFindExamples={onFindExamples}
              library={library}
              autoFocus={railState.reason === 'user'}
            />
          )}
          <div className="bottom-dock">
            {showNodes && <NodesMenu boardId={boardId} onClose={() => setNodesOpen(false)} />}
            <BottomToolbar onNodes={() => setNodesOpen((o) => !o)} plugins={plugins} explore={explore} nodesOpen={showNodes} />
          </div>
          <AgentCard boardId={boardId} />
        </section>
      </div>
      <RightDrawer boardId={boardId} />
    </div>
  )
}
