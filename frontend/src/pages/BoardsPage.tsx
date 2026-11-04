import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { createBoard, keys, listBoards } from '../api'
import { useDemo } from '../demo'
import { presentShowcase } from '../landing/showcase'
import { ShowcaseCards } from '../landing/ShowcaseCards'
import { Link } from '../Link'
import { DemoBadge } from '../panels/DemoBadge'
import { navigate } from '../router'

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function BoardsPage() {
  const qc = useQueryClient()
  const boards = useQuery({ queryKey: keys.boards, queryFn: listBoards })
  const [title, setTitle] = useState('')
  const id = useId()
  const { locked } = useDemo()
  // the demo boards get cards above; the list holds the rest so none shows twice
  const demoIds = new Set(presentShowcase(boards.data).map((b) => b.boardId))
  const own = boards.data?.filter((b) => !demoIds.has(b.id))
  const create = useMutation({
    mutationFn: (t: string) => createBoard({ title: t }),
    onSuccess: (b) => {
      qc.setQueryData(keys.board(b.id), b)
      void qc.invalidateQueries({ queryKey: keys.boards })
      navigate(`/boards/${encodeURIComponent(b.id)}`)
    },
  })

  return (
    <main className="boards-page">
      <header>
        <p className="eyebrow">Design Language Engine</p>
        <h1>Boards</h1>
        <DemoBadge />
      </header>
      <form
        className="new-board"
        onSubmit={(e) => {
          e.preventDefault()
          const t = title.trim()
          if (t && !locked) create.mutate(t)
        }}
      >
        <label htmlFor={id}>New board</label>
        <div className="row">
          <input id={id} value={title} disabled={locked} placeholder="e.g. Field watch, warmer" onChange={(e) => setTitle(e.target.value)} />
          <button type="submit" className="btn" disabled={locked || !title.trim() || create.isPending}>
            Create board
          </button>
        </div>
        {locked && <p className="muted small">This is a read-only demo: open a board below, or unlock to create one.</p>}
        {create.isError && (
          <p className="error small" role="alert">
            {create.error.message}
          </p>
        )}
      </form>
      {demoIds.size > 0 && (
        <section className="showcase" aria-labelledby={`${id}-demo`}>
          <h2 id={`${id}-demo`}>Demo boards</h2>
          <p className="muted">Recorded end to end by the agent. Watch it work, or open one and look around.</p>
          <ShowcaseCards boards={boards.data} />
        </section>
      )}
      {boards.isLoading && <p className="muted">Loading boards…</p>}
      {boards.isError && (
        <p className="error" role="alert">
          Could not load boards: {boards.error.message}
        </p>
      )}
      {own && own.length === 0 && demoIds.size === 0 && <p className="muted">No boards yet. Name your first one above.</p>}
      {own && own.length > 0 && demoIds.size > 0 && <h2 className="board-list-title">Your boards</h2>}
      {own && own.length > 0 && (
        <ul className="board-list">
          {own.map((b) => (
            <li key={b.id}>
              <Link href={`/boards/${encodeURIComponent(b.id)}`}>
                <b>{b.title}</b>
                <span className="muted small">Updated {when(b.updated_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
