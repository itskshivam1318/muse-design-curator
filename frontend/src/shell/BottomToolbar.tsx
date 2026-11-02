import { LOCKED_TITLE, useDemo } from '../demo'
import { setTool, type Tool, useTool } from './tools'

interface Props {
  onNodes: () => void
  /** Plugins are on: show Nodes. */
  plugins: boolean
  /** The Nodes menu is open (for aria-expanded). */
  nodesOpen?: boolean
}

const TOOLS: { tool: Tool; label: string; key: string }[] = [
  { tool: 'select', label: 'Select', key: 'Escape' },
  { tool: 'note', label: 'Note', key: 'N' },
]

/** Floating centre-bottom: the board tools, then Nodes (a menu of the board's added plugins). */
export function BottomToolbar({ onNodes, plugins, nodesOpen = false }: Props) {
  const active = useTool()
  const { locked } = useDemo()
  return (
    <div className="bottom-toolbar" role="toolbar" aria-label="Tools">
      {TOOLS.map((t) => (
        <button
          key={t.tool}
          type="button"
          className="tool-btn"
          aria-pressed={active === t.tool}
          aria-keyshortcuts={t.key}
          onClick={() => setTool(t.tool)}
        >
          {t.label}
        </button>
      ))}
      {plugins && (
        <button
          type="button"
          className="tool-btn"
          aria-haspopup="dialog"
          aria-expanded={nodesOpen}
          disabled={locked}
          title={locked ? LOCKED_TITLE : undefined}
          onClick={onNodes}
        >
          Nodes
        </button>
      )}
    </div>
  )
}
