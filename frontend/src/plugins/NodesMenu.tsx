import { useEffect, useRef } from 'react'

/** Stub until Task 12: the Nodes menu (the board's added plugins; choosing one makes a node). */
export function NodesMenu({ boardId, onClose }: { boardId: string; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div
      ref={ref}
      className="nodes-menu"
      role="dialog"
      aria-label="Nodes"
      tabIndex={-1}
      data-board={boardId}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        e.stopPropagation()
        onClose()
      }}
    >
      <p className="muted small">Nodes will appear here once plugins are added to this board.</p>
    </div>
  )
}
