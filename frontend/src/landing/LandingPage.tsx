import { useQuery } from '@tanstack/react-query'
import { keys, listBoards } from '../api'
import { Link } from '../Link'
import { presentShowcase, SHOWCASE } from './showcase'
import { ShowcaseCards } from './ShowcaseCards'
import './landing.css'

export function LandingPage() {
  const boards = useQuery({ queryKey: keys.boards, queryFn: listBoards })
  const cards = presentShowcase(boards.data)

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
      <ShowcaseCards boards={boards.data} />
      <p>
        <Link href="/boards">All boards</Link>
      </p>
    </main>
  )
}
