/** Plugin options on the board: Keep one, or Clear every option a node still stands behind (undoable). */
import type { QueryClient } from '@tanstack/react-query'
import { clearOptions, type Item, keepOption, keys, restoreItem } from '../api'
import { upsertItems } from '../events'
import { undoHistory } from './history'

/** Keep an option: its outline goes at once; a refusal puts it back. */
export async function keepOptionItem(qc: QueryClient, boardId: string, id: string): Promise<void> {
  const set = (run: string | null) =>
    qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.map((i) => (i.id === id ? { ...i, option_run_id: run } : i)))
  const before = qc.getQueryData<Item[]>(keys.items(boardId))?.find((i) => i.id === id)?.option_run_id ?? null
  set(null)
  try {
    upsertItems(qc, boardId, [await keepOption(id)])
  } catch (e) {
    set(before)
    throw e
  }
}

/** Remove a node's standing options; one undo step brings every one back. Resolves to how many went. */
export async function clearNodeOptions(qc: QueryClient, boardId: string, nodeId: string): Promise<number> {
  const { removed_item_ids: ids } = await clearOptions(nodeId)
  if (ids.length === 0) return 0
  const gone = new Set(ids)
  qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.filter((i) => !gone.has(i.id)))
  undoHistory.pushRevert(() => {
    void Promise.all(ids.map((id) => restoreItem(id)))
      .then((items) => upsertItems(qc, boardId, items))
      .catch(() => void qc.invalidateQueries({ queryKey: keys.items(boardId) }))
  })
  return ids.length
}
