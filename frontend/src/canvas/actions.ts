import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { deleteItem, type Item, keys, patchItem } from '../api'
import { upsertItems } from '../events'
import { createMoveHistory, type Move } from './history'
import { selection } from './selection'
import { track } from '../telemetry'

/** Item mutations with optimistic cache updates; the server's SSE echo confirms them. */
export function useItemActions(boardId: string) {
  const qc = useQueryClient()
  const [history] = useState(createMoveHistory)
  const [error, setError] = useState<string | null>(null)

  const resync = useCallback(() => {
    void qc.invalidateQueries({ queryKey: keys.items(boardId) })
  }, [qc, boardId])

  const fail = useCallback(
    (msg: string) => (e: unknown) => {
      setError(e instanceof Error ? `${msg}: ${e.message}` : msg)
      resync()
    },
    [resync],
  )

  const applyPositions = useCallback(
    (moves: Move[], which: 'from' | 'to') => {
      const byId = new Map(moves.map((m) => [m.id, m[which]]))
      qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
        old?.map((i) => (byId.has(i.id) ? { ...i, ...byId.get(i.id)! } : i)),
      )
      for (const [id, p] of byId) patchItem(id, { x: p.x, y: p.y }).catch(fail('Could not save position'))
    },
    [qc, boardId, fail],
  )

  return useMemo(
    () => ({
      error,
      clearError: () => setError(null),
      history,
      move(moves: Move[]) {
        history.push(moves)
        applyPositions(moves, 'to')
      },
      undo(): boolean {
        const last = history.pop()
        if (!last) return false
        applyPositions(last, 'from')
        return true
      },
      remove(ids: readonly string[]) {
        if (ids.length === 0) return
        track('item.remove', { detail: { items: [...ids] } })
        const gone = new Set(ids)
        qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.filter((i) => !gone.has(i.id)))
        selection.clear()
        for (const id of ids) deleteItem(id).catch(fail('Could not remove item'))
      },
      /** Mark as "not this" (counter-example); if every one already is, turn them back into references. */
      toggleNotThis(items: readonly Item[]) {
        if (items.length === 0) return
        const role: Item['role'] = items.every((i) => i.role === 'counter_example') ? 'reference' : 'counter_example'
        const ids = new Set(items.map((i) => i.id))
        track('item.role', { detail: { items: [...ids], role } })
        qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.map((i) => (ids.has(i.id) ? { ...i, role } : i)))
        for (const id of ids) patchItem(id, { role }).catch(fail('Could not update item'))
      },
      async chooseFrame(itemId: string, frameId: string) {
        try {
          const item = await patchItem(itemId, { chosen_frame_id: frameId })
          upsertItems(qc, boardId, [item])
          await qc.invalidateQueries({ queryKey: keys.frames(itemId) })
        } catch (e) {
          fail('Could not choose frame')(e)
        }
      },
    }),
    [error, history, applyPositions, qc, boardId, fail],
  )
}

export type ItemActions = ReturnType<typeof useItemActions>
