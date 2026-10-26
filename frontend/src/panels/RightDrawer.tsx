import { createElement } from 'react'
import { selection, useSelection } from '../canvas/selection'
import { getDrawerPanel } from './drawerRegistry'

/** The right-drawer slot; empty until a panel is registered (see drawerRegistry.ts). */
export function RightDrawer({ boardId }: { boardId: string }) {
  const { drawer } = useSelection()
  const panel = drawer ? getDrawerPanel(drawer.kind) : undefined
  if (!drawer || !panel) return null
  return (
    <aside className="right-drawer" aria-label={`${drawer.kind} panel`}>
      {createElement(panel, { boardId, itemId: drawer.itemId, onClose: () => selection.closeDrawer() })}
    </aside>
  )
}
