import { BoardPage } from './pages/BoardPage'
import { BoardsPage } from './pages/BoardsPage'
import { Link } from './Link'
import { matchRoute, usePathname } from './router'

export default function App() {
  const route = matchRoute(usePathname())
  switch (route.name) {
    case 'boards':
      return <BoardsPage />
    case 'board':
      return <BoardPage key={route.id} boardId={route.id} />
    default:
      return (
        <main className="page-message">
          <h1>Page not found</h1>
          <Link href="/">All boards</Link>
        </main>
      )
  }
}
