/** Registers the right-drawer panels (imported once by BoardPage). Each loads on first open. */
import { lazy } from 'react'
import { registerDrawerPanel } from './drawerRegistry'

registerDrawerPanel('inspect', lazy(() => import('./InspectPanel').then((m) => ({ default: m.InspectPanel }))))
registerDrawerPanel('compare', lazy(() => import('./ComparePanel').then((m) => ({ default: m.ComparePanel }))))
