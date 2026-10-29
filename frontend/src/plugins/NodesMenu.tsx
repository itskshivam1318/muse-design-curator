/** The Nodes menu (bottom toolbar): the board's added plugins; choosing one places a node with the selection as inputs. */
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { type Item, keys, type PluginInfo } from '../api'
import { unionBounds } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { useSelection } from '../canvas/selection'
import { LOCKED_TITLE, useDemo } from '../demo'
import { useBoardPlugins, usePlugins } from '../queries'
import { openRail } from '../shell/tools'
import { acceptsItem, createNodeFromSelection, placeNode } from './nodeLogic'
import { PluginTile } from './PluginsPanel'
import { viewportCenter } from './stores'

export function NodesMenu({ boardId, onClose }: { boardId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const { locked } = useDemo()
  const ref = useRef<HTMLDivElement>(null)
  const all = usePlugins().data
  const added = useBoardPlugins(boardId).data
  const { selected } = useSelection()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => ref.current?.focus(), [])

  const plugins = all && added ? all.filter((p) => added.includes(p.id)) : null
  const boardItems = qc.getQueryData<Item[]>(keys.items(boardId)) ?? []
  const chosen = boardItems.filter((i) => selected.includes(i.id) && !i.staged)

  const place = async (plugin: PluginInfo) => {
    const inputs = chosen.filter((i) => acceptsItem(plugin, i))
    const at = placeNode(unionBounds(inputs.map(itemBounds)), viewportCenter())
    setBusy(true)
    setError(null)
    try {
      await createNodeFromSelection(qc, boardId, plugin, at)
      onClose()
    } catch {
      setError(`Could not add a ${plugin.name} node`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      ref={ref}
      className="nodes-menu"
      role="dialog"
      aria-label="Nodes"
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        e.stopPropagation()
        onClose()
      }}
    >
      {!plugins ? (
        <p className="muted small">Loading…</p>
      ) : plugins.length === 0 ? (
        <>
          <p className="muted small">No plugins on this board yet.</p>
          <button
            type="button"
            className="btn-quiet small"
            onClick={() => {
              onClose()
              openRail('plugins')
            }}
          >
            Open Plugins
          </button>
        </>
      ) : (
        <>
          <p className="muted small nodes-menu-hint">
            {chosen.length > 0
              ? `The new node takes the ${chosen.length === 1 ? 'selected item' : `${chosen.length} selected items`} it can read.`
              : 'Select items first to use them as inputs, or drag them onto the node later.'}
          </p>
          <ul className="nodes-menu-list" aria-label="Add a node">
            {plugins.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="nodes-menu-item"
                  disabled={locked || busy}
                  title={locked ? LOCKED_TITLE : undefined}
                  onClick={() => void place(p)}
                >
                  <PluginTile plugin={p} size={24} />
                  <span className="nodes-menu-name">{p.name}</span>
                  {p.status !== 'available' && <span className="plugin-tag">Not connected</span>}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {error && (
        <p className="small plugin-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
