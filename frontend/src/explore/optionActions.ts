/**
 * Option edits shared by the axis popover and the drawer: dismiss an option.
 * It lands in the board's undo stack, so ⌘Z puts it back wherever it was made.
 */
import type { QueryClient } from '@tanstack/react-query'
import { type Exploration, type ExploreOption, keys, patchOption } from '../api'
import { undoHistory } from '../canvas/history'
import { hoverStore, setHoveredOption } from './hover'
import { withOption } from './logic'

/** Resync after an undo the server refused (the event stream may also have moved on). */
const resync = (qc: QueryClient, boardId: string) => () => {
  void qc.invalidateQueries({ queryKey: keys.explorations(boardId) })
}

/** Dismiss an option (drawer or axis popover Dismiss); undo reopens it. */
export async function dismissOption(qc: QueryClient, boardId: string, option: ExploreOption): Promise<void> {
  const next = await patchOption(option.id, { status: 'dismissed' })
  qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withOption(old, next))
  if (hoverStore.get() === option.id) setHoveredOption(null)
  undoHistory.pushRevert(() => {
    // "open" here; the server makes it "visualized" again when it has generated images
    patchOption(option.id, { status: 'open' })
      .then((o) => qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withOption(old, o)))
      .catch(resync(qc, boardId))
  })
}
