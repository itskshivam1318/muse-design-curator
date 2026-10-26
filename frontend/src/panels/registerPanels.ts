/** Registers the right-drawer panels (imported once by BoardPage). */
import { ComparePanel } from './ComparePanel'
import { registerDrawerPanel } from './drawerRegistry'
import { InspectPanel } from './InspectPanel'
import { VaryPanel } from './VaryPanel'

registerDrawerPanel('inspect', InspectPanel)
registerDrawerPanel('vary', VaryPanel)
registerDrawerPanel('compare', ComparePanel)
