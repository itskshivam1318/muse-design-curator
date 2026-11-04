import { useQuery } from '@tanstack/react-query'
import { itemThumbUrl, keys, listBoards } from '../api'
import { Link } from '../Link'
import { SHOWCASE } from './showcase'
import './landing.css'

export function LandingPage() {
  const boards = useQuery({ queryKey: keys.boards, queryFn: listBoards })
  const here = new Set((boards.data ?? []).map((b) => b.id))
  const cards = SHOWCASE.boards.filter((b) => here.has(b.boardId))

  return (
    <main className="landing">
      <header>
        <h1>Muse</h1>
        <p>
          Picking references is easy; saying "like this one, but different in X" is not. Muse reads each picture along named dimensions, so you can
          change one and keep the rest.
        </p>
        <p>Words like "premium" or "clean" mean different things to different people. Muse pins them to what your own pictures share.</p>
      </header>
      {SHOWCASE.videoUrl && <video className="landing-video" controls src={SHOWCASE.videoUrl} />}
      {boards.isSuccess && cards.length === 0 && <p className="muted">The demo boards are not on this server yet.</p>}
      {boards.isError && <p className="muted">Could not load the demo boards.</p>}
      <div className="landing-cards">
        {cards.map((b) => (
          <article key={b.boardId} className="landing-card">
            <img src={itemThumbUrl(b.coverItemId)} alt="" loading="lazy" />
            <h2>{b.title}</h2>
            <p className="muted">{b.line}</p>
            <div className="landing-actions">
              <Link className="btn" href={`/boards/${b.boardId}?replay=${b.runId}`}>
                Show me how
              </Link>
              <Link href={`/boards/${b.boardId}`}>Look around</Link>
            </div>
          </article>
        ))}
      </div>
      <p>
        <Link href="/boards">All boards</Link>
      </p>
    </main>
  )
}
