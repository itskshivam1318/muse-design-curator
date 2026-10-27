/**
 * Option edits shared by the canvas notes and the drawer: move a note, dismiss an option.
 * Each one lands in the board's undo stack, so ⌘Z puts it back wherever it was made.
 */
import type { QueryClient } from '@tanstack/react-query'
import { type Exploration, type ExploreOption, keys, patchOption, type Point } from '../api'
import { undoHistory } from '../canvas/history'
import { hoverStore, setHoveredOption } from './hover'
import { withOption } from './logic'

const findOption = (list: Exploration[] | undefined, id: string) =>
  list?.flatMap((e) => e.options).find((o) => o.id === id)

/** Put one option's position in the cache, keeping whatever else changed meanwhile. */
function setPosition(qc: QueryClient, boardId: string, optionId: string, p: { x: number | null; y: number | null }) {
  qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => {
    const cur = findOption(old, optionId)
    return cur ? withOption(old, { ...cur, x: p.x, y: p.y }) : old
  })
}

/** Resync after an undo the server refused (the event stream may also have moved on). */
const resync = (qc: QueryClient, boardId: string) => () => {
  void qc.invalidateQueries({ queryKey: keys.explorations(boardId) })
}

/**
 * Save a note at `to` (shown at once). A refused save puts the note back where it was and
 * rethrows; a saved one is undoable back to `from`, where the note was drawn before the drag.
 */
export async function moveOption(
  qc: QueryClient,
  boardId: string,
  optionId: string,
  from: Point,
  to: Point,
  record = true,
): Promise<void> {
  const before = findOption(qc.getQueryData<Exploration[]>(keys.explorations(boardId)), optionId)
  if (!before) return
  setPosition(qc, boardId, optionId, to)
  try {
    await patchOption(optionId, { x: to.x, y: to.y })
  } catch (e) {
    setPosition(qc, boardId, optionId, before)
    throw e
  }
  if (record) {
    undoHistory.pushRevert(() => {
      moveOption(qc, boardId, optionId, to, from, false).catch(resync(qc, boardId))
    })
  }
}

/** Dismiss an option (drawer Dismiss or the note's ×); undo reopens it. */
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
