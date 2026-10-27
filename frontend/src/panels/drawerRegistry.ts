/**
 * Right-hand drawer registry. Task 18 registers its Inspect and Vary panels here:
 *   registerDrawerPanel('inspect', InspectPanel)
 * The canvas opens a drawer with selection.openDrawer(kind, itemId) (toolbar buttons, I / V keys);
 * <RightDrawer> renders whichever panel is registered for the open kind.
 */
import type { ComponentType, LazyExoticComponent } from 'react'

export interface DrawerPanelProps {
  boardId: string
  itemId: string
  params?: Record<string, unknown>
  onClose: () => void
  /** Public demo, not unlocked: panels show values but disable their editors. */
  locked?: boolean
}

export type DrawerPanel = ComponentType<DrawerPanelProps> | LazyExoticComponent<ComponentType<DrawerPanelProps>>

const panels = new Map<string, DrawerPanel>()

export function registerDrawerPanel(kind: string, panel: DrawerPanel): void {
  panels.set(kind, panel)
}

export function getDrawerPanel(kind: string): DrawerPanel | undefined {
  return panels.get(kind)
}

export function hasDrawerPanel(kind: string): boolean {
  return panels.has(kind)
}
