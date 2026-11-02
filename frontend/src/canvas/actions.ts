import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  analyseItem,
  ApiError,
  createNote,
  deleteItem,
  type Exploration,
  type Item,
  keys,
  patchExploration,
  patchItem,
  patchOption,
  visualizeNote,
} from '../api'
import { setVisualizing, upsertItems } from '../events'
import type { ReleasePlan } from '../living/release'
import { undoHistory as history } from './history'
import { selection } from './selection'
import { track } from '../telemetry'

/** Item mutations with optimistic cache updates; the server's SSE echo confirms them. */
export function useItemActions(boardId: string) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => history.clear(), [boardId])

  const resync = useCallback(() => {
    void qc.invalidateQueries({ queryKey: keys.items(boardId) })
  }, [qc, boardId])

  const report = useCallback(
    (msg: string) => (e: unknown) => setError(e instanceof Error ? `${msg}: ${e.message}` : msg),
    [],
  )
  const fail = useCallback(
    (msg: string) => (e: unknown) => {
      report(msg)(e)
      resync()
    },
    [report, resync],
  )

  /** A release touches items and explorations: a failed write puts both back as the server has them. */
  const failRelease = useCallback(
    (e: unknown) => {
      fail('Could not save position')(e)
      void qc.invalidateQueries({ queryKey: keys.explorations(boardId) })
    },
    [fail, qc, boardId],
  )

  /**
   * A release plan applied one way ('to') or back ('from'): the caches at once, then the writes.
   * Locked (the public demo): only item positions are written (they are open there); sizes, hub
   * offsets and dock flags stay local.
   */
  const applyRelease = useCallback(
    (plan: ReleasePlan, which: 'from' | 'to', locked: boolean) => {
      const pos = new Map(plan.moves.map((m) => [m.id, m[which]]))
      const size = new Map(plan.dock.map((d) => [d.itemId, which === 'to' ? d.size : d.from]))
      const hub = new Map(plan.hubs.map((h) => [h.explorationId, which === 'to' ? h.to : h.from]))
      const undocked = new Map(plan.dock.map((d) => [d.optionId, which === 'to' ? d.undocked : !d.undocked]))
      qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
        old?.map((i) => (pos.has(i.id) || size.has(i.id) ? { ...i, ...pos.get(i.id), ...size.get(i.id) } : i)),
      )
      qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) =>
        old?.map((e) => {
          if (!hub.has(e.id) && !e.options.some((o) => undocked.has(o.id))) return e
          const off = hub.get(e.id)
          const options = e.options.map((o) => (undocked.has(o.id) ? { ...o, undocked: undocked.get(o.id)! } : o))
          return hub.has(e.id) ? { ...e, dx: off?.dx ?? null, dy: off?.dy ?? null, options } : { ...e, options }
        }),
      )
      for (const id of new Set([...pos.keys(), ...size.keys()])) {
        const body = { ...pos.get(id), ...(locked ? undefined : size.get(id)) }
        if (Object.keys(body).length > 0) patchItem(id, body).catch(failRelease)
      }
      if (locked) return
      for (const [id, off] of hub) patchExploration(id, { dx: off?.dx ?? null, dy: off?.dy ?? null }).catch(failRelease)
      for (const [id, u] of undocked) patchOption(id, { undocked: u }).catch(failRelease)
    },
    [qc, boardId, failRelease],
  )

  const dropNote = useCallback(
    (id: string) => {
      qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.filter((i) => i.id !== id))
      deleteItem(id).catch(fail('Could not remove note'))
    },
    [qc, boardId, fail],
  )

  const addNote = useCallback(
    async (at: { x: number; y: number; w: number; h: number }, text: string): Promise<Item | null> => {
      try {
        const body = { text, x: Math.round(at.x), y: Math.round(at.y), w: at.w, h: Math.round(at.h) }
        const item = await createNote(boardId, body)
        upsertItems(qc, boardId, [item])
        return item
      } catch (e) {
        report('Could not add note')(e)
        return null
      }
    },
    [qc, boardId, report],
  )

  const setNoteText = useCallback(
    (id: string, note_text: string, h: number) => {
      qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.map((i) => (i.id === id ? { ...i, note_text, h } : i)))
      patchItem(id, { note_text, h }).catch(fail('Could not save note'))
    },
    [qc, boardId, fail],
  )

  return useMemo(
    () => ({
      error,
      clearError: () => setError(null),
      history,
      /**
       * Everything one pointer release changed (items, docked takes carried along, hub offsets, dock
       * changes): applied at once and written, as one undo step.
       */
      commitRelease(plan: ReleasePlan, opts: { locked: boolean }) {
        if (plan.moves.length + plan.hubs.length + plan.dock.length === 0) return
        applyRelease(plan, 'to', opts.locked)
        history.pushRevert(() => applyRelease(plan, 'from', opts.locked))
      },
      undo(): boolean {
        const last = history.pop()
        if (!last) return false
        last.revert()
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
      /** A note typed on the canvas; ⌘Z removes it again. */
      async createNote(at: { x: number; y: number; w: number; h: number }, text: string) {
        const item = await addNote(at, text)
        if (item) history.pushRevert(() => dropNote(item.id))
        return item
      },
      /** New text for a note (and the height it now draws at); ⌘Z puts the old text back. */
      editNote(note: Item, text: string, h: number) {
        const before = { text: note.note_text ?? '', h: note.h }
        setNoteText(note.id, text, h)
        history.pushRevert(() => setNoteText(note.id, before.text, before.h))
      },
      /** Delete from the note's menu; ⌘Z writes it back (as a new note in the same spot). */
      deleteNote(note: Item) {
        dropNote(note.id)
        const text = note.note_text ?? ''
        if (text.trim()) history.pushRevert(() => void addNote(note, text))
      },
      /** Generate an image from the note. Shown as visualizing at once; a refusal clears it. */
      visualizeNote(noteId: string) {
        setVisualizing(noteId, true)
        visualizeNote(noteId).catch((e: unknown) => {
          if (e instanceof ApiError && e.status === 409) return // already under way: its events will follow
          setVisualizing(noteId, false)
          report('Could not visualize note')(e)
        })
      },
      /** Analyse the item again (counts against the board's daily limit). Throws the refusal (a 429
       *  DAILY_LIMIT, a 409 while one is queued) for the caller to show. */
      async reanalyse(itemId: string) {
        await analyseItem(itemId)
        qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
          old?.map((i) => (i.id === itemId ? { ...i, parse_status: 'pending', parse_error_code: null } : i)),
        )
        await qc.invalidateQueries({ queryKey: keys.analysis(itemId) })
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
    [error, applyRelease, qc, boardId, fail, report, addNote, dropNote, setNoteText],
  )
}

export type ItemActions = ReturnType<typeof useItemActions>
