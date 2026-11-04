import { type BoardSummary, itemThumbUrl } from '../api'
import { Link } from '../Link'
import { presentShowcase } from './showcase'
import './landing.css'

export function ShowcaseCards({ boards }: { boards: BoardSummary[] | undefined }) {
  const cards = presentShowcase(boards)
  if (cards.length === 0) return null
  return (
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
  )
}
