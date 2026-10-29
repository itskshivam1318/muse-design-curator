import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ApiError,
  createNote,
  deleteItem,
  type ExploreOption,
  type Item,
  keys,
  patchItem,
  type Point,
  visualizeNote,
} from '../api'
import { setVisualizing, upsertItems } from '../events'
import { dismissOption, moveOption } from '../explore/optionActions'
import { type Move, undoHistory as history } from './history'
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
      move(moves: Move[]) {
        history.push(moves)
        applyPositions(moves, 'to')
      },
      undo(): boolean {
        const last = history.pop()
        if (!last) return false
        if (last.kind === 'moves') applyPositions(last.moves, 'from')
        else last.revert()
        return true
      },
      /** Drop an explore note at a new spot; a refused save puts it back. Undoable. */
      moveOption(optionId: string, from: Point, to: Point) {
        moveOption(qc, boardId, optionId, from, to).catch(report('Could not save note position'))
      },
      /** The note's ×: same as Dismiss in the drawer. Undoable. */
      dismissOption(option: ExploreOption) {
        dismissOption(qc, boardId, option).catch(report('Could not dismiss'))
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
    [error, applyPositions, qc, boardId, fail, report, addNote, dropNote, setNoteText],
  )
}

export type ItemActions = ReturnType<typeof useItemActions>
