import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { createBoard, keys, listBoards } from '../api'
import { Link } from '../Link'
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
      </header>
      <form
        className="new-board"
        onSubmit={(e) => {
          e.preventDefault()
          const t = title.trim()
          if (t) create.mutate(t)
        }}
      >
        <label htmlFor={id}>New board</label>
        <div className="row">
          <input id={id} value={title} placeholder="e.g. Field watch, warmer" onChange={(e) => setTitle(e.target.value)} />
          <button type="submit" className="btn" disabled={!title.trim() || create.isPending}>
            Create board
          </button>
        </div>
        {create.isError && (
          <p className="error small" role="alert">
            {create.error.message}
          </p>
        )}
      </form>
      {boards.isLoading && <p className="muted">Loading boards…</p>}
      {boards.isError && (
        <p className="error" role="alert">
          Could not load boards: {boards.error.message}
        </p>
      )}
      {boards.data && boards.data.length === 0 && <p className="muted">No boards yet. Name your first one above.</p>}
      {boards.data && boards.data.length > 0 && (
        <ul className="board-list">
          {boards.data.map((b) => (
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
