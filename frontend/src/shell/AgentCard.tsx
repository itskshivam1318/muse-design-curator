import { useState } from 'react'
import { useSelection } from '../canvas/selection'
import { useActivity } from './activity'

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

/**
 * Floating bottom-right: "Muse", the latest thing that happened on the board, and the agent's input
 * (a shell this round: visible, disabled). Gives way to the right drawer.
 */
export function AgentCard({ boardId }: { boardId: string }) {
  const entries = useActivity()
  const { drawer } = useSelection()
  const [expanded, setExpanded] = useState(false)
  if (drawer) return null
  const latest = entries.at(-1)
  const inputId = `agent-input-${boardId}`
  return (
    <aside className="agent-card" aria-label="Muse agent">
      <div className="agent-head">
        <span className="agent-name">Muse</span>
        <button
          type="button"
          className="icon-btn"
          aria-label="Show activity"
          aria-expanded={expanded}
          onClick={() => setExpanded((x) => !x)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
            {expanded ? <path d="M3 5l4 4 4-4" /> : <path d="M8.5 2.5h3v3M5.5 11.5h-3v-3M11.5 2.5L8 6M2.5 11.5L6 8" />}
          </svg>
        </button>
      </div>
      {expanded ? (
        entries.length > 0 ? (
          <ol className="agent-log" aria-label="Activity">
            {[...entries].reverse().map((e, i) => (
              <li key={`${e.at}-${i}`}>
                <span>{e.text}</span> <time dateTime={e.at}>{clock(e.at)}</time>
              </li>
            ))}
          </ol>
        ) : (
          <p className="agent-latest">Nothing yet.</p>
        )
      ) : (
        <p className="agent-latest" aria-live="polite">
          {latest?.text ?? 'Nothing yet.'}
        </p>
      )}
      <div className="agent-ask">
        <label htmlFor={inputId} className="sr-only">
          Message Muse
        </label>
        <input id={inputId} type="text" placeholder="Agent coming soon" disabled />
        <button type="button" className="agent-send" aria-label="Send" disabled>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M7 11.5v-9M3 6.5l4-4 4 4" />
          </svg>
        </button>
      </div>
    </aside>
  )
}
