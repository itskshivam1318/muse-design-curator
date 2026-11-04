import { useState } from 'react'
import { BoardPage } from './pages/BoardPage'
import { BoardsPage } from './pages/BoardsPage'
import { useDemo } from './demo'
import { LandingPage } from './landing/LandingPage'
import { Link } from './Link'
import { matchRoute, usePathname } from './router'

export default function App() {
  const route = matchRoute(usePathname())
  const { demoMode, settled } = useDemo()
  // latch: a failed status query refetches when BoardsPage mounts its own observer, which would flip this back
  const [known, setKnown] = useState(false)
  if (settled && !known) setKnown(true)
  switch (route.name) {
    case 'home':
      if (!settled && !known) return <main className="page-message" />
      return demoMode ? <LandingPage /> : <BoardsPage />
    case 'boards':
      return <BoardsPage />
    case 'board':
      return <BoardPage key={route.id} boardId={route.id} />
    default:
      return (
        <main className="page-message">
          <h1>Page not found</h1>
          <Link href="/boards">All boards</Link>
        </main>
      )
  }
}
