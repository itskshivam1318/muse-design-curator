/** The Plugins rail panel: workflow packs on the left, the chosen pack's plugins (Add / Added) on the right. */
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addBoardPlugin, keys, type PluginInfo, removeBoardPlugin } from '../api'
import { LOCKED_TITLE, useDemo } from '../demo'
import { useBoardPlugins, usePacks, usePlugins } from '../queries'
import './plugins.css'

export function PluginTile({ plugin, size = 32 }: { plugin: Pick<PluginInfo, 'mark' | 'tint' | 'ink'>; size?: number }) {
  return (
    <span
      className="plugin-tile"
      aria-hidden="true"
      style={{ background: plugin.tint, color: plugin.ink, width: size, height: size }}
    >
      {plugin.mark}
    </span>
  )
}

export function PluginsPanel({ boardId }: { boardId: string }) {
  const qc = useQueryClient()
  const { locked } = useDemo()
  const plugins = usePlugins()
  const packs = usePacks()
  const added = useBoardPlugins(boardId).data ?? []
  const [packId, setPackId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [docsOpen, setDocsOpen] = useState(false)

  if (plugins.isError || packs.isError) return <p className="muted small">Could not load plugins.</p>
  if (!plugins.data || !packs.data) return <p className="muted small">Loading plugins…</p>

  const byId = new Map(plugins.data.map((p) => [p.id, p]))
  const list = packs.data.map((p) => ({ ...p, plugins: p.plugin_ids.flatMap((id) => byId.get(id) ?? []) }))
  const pack = list.find((p) => p.id === packId) ?? list[0]
  const q = query.trim().toLowerCase()
  const shown = (pack?.plugins ?? []).filter(
    (p) => !q || `${p.name} ${p.description} ${p.runs_on}`.toLowerCase().includes(q),
  )

  const toggle = async (plugin: PluginInfo) => {
    const on = added.includes(plugin.id)
    setBusy(plugin.id)
    setError(null)
    try {
      if (on) {
        await removeBoardPlugin(boardId, plugin.id)
        qc.setQueryData<string[]>(keys.boardPlugins(boardId), (old) => (old ?? []).filter((id) => id !== plugin.id))
      } else {
        const ids = await addBoardPlugin(boardId, plugin.id)
        qc.setQueryData<string[]>(keys.boardPlugins(boardId), ids)
      }
    } catch {
      setError(on ? `Could not remove ${plugin.name}` : `Could not add ${plugin.name}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="plugins-panel">
      <div className="plugins-body">
        <nav className="plugin-packs" aria-label="Packs">
          {list.map((p) => (
            <button
              key={p.id}
              type="button"
              className="plugin-pack"
              aria-pressed={p.id === pack?.id}
              onClick={() => setPackId(p.id)}
            >
              <span>{p.name}</span>
              <span className="plugin-pack-count">{p.plugins.length}</span>
            </button>
          ))}
          <p className="muted small">Packs are suggestions. Any plugin can be added to any board.</p>
        </nav>
        <div className="plugin-list-wrap">
          {pack && (
            <div className="plugin-pack-head">
              <h3>{pack.name}</h3>
              <p className="muted small">{pack.about}</p>
            </div>
          )}
          <label className="sr-only" htmlFor={`plugin-search-${boardId}`}>
            Search plugins
          </label>
          <input
            id={`plugin-search-${boardId}`}
            type="search"
            className="plugin-search"
            placeholder="Search plugins"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {error && (
            <p className="small plugin-error" role="alert">
              {error}
            </p>
          )}
          <ul className="plugin-list" aria-label={`Plugins in ${pack?.name ?? 'this pack'}`}>
            {shown.map((p) => {
              const on = added.includes(p.id)
              return (
                <li key={p.id} className="plugin-row">
                  <PluginTile plugin={p} />
                  <span className="plugin-text">
                    <span className="plugin-name">{p.name}</span>
                    <span className="plugin-does">{p.description}</span>
                    <span className="plugin-runs">
                      runs on {p.runs_on}
                      {p.status !== 'available' && <span className="plugin-tag">Not connected</span>}
                    </span>
                  </span>
                  <button
                    type="button"
                    className={on ? 'plugin-add is-added' : 'plugin-add'}
                    aria-label={`${on ? 'Added' : 'Add'} ${p.name}`}
                    title={locked ? LOCKED_TITLE : on ? 'Remove from this board' : undefined}
                    disabled={locked || busy === p.id}
                    onClick={() => void toggle(p)}
                  >
                    {on ? 'Added' : 'Add'}
                  </button>
                </li>
              )
            })}
          </ul>
          {shown.length === 0 && <p className="muted small">No plugins match.</p>}
        </div>
      </div>
      <div className="plugins-foot">
        <p className="muted small">
          A plugin declares what it reads from the board, what it writes back, and which model or service it calls.
        </p>
        <button type="button" className="btn-quiet small" aria-expanded={docsOpen} onClick={() => setDocsOpen((o) => !o)}>
          Build a plugin
        </button>
        {docsOpen && (
          <p className="small">
            See <code>docs/plugins.md</code> in the project.
          </p>
        )}
      </div>
    </div>
  )
}
