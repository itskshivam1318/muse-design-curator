import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { addLink as apiAddLink, ApiError, type Point, type UploadOrigin, uploadFiles } from '../api'
import { upsertItems } from '../events'
import { partitionFiles, type Rejected } from '../validation'

export interface UploadJob {
  id: number
  label: string
  progress: number // 0..1
  state: 'uploading' | 'done' | 'failed'
  errors: Rejected[]
}

const AUTO_DISMISS_MS = 2500
let nextId = 1

/**
 * Upload / link ingest with client-side validation, XHR progress and per-file errors.
 * In-flight uploads are aborted on unmount (leaving or switching boards) or on Cancel, and nothing
 * touches state once the hook has unmounted.
 */
export function useAddFlow(boardId: string) {
  const qc = useQueryClient()
  const [jobs, setJobs] = useState<UploadJob[]>([])
  const aborts = useRef(new Map<number, () => void>())
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>())
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    const pending = aborts.current
    const timeouts = timers.current
    return () => {
      alive.current = false
      for (const abort of pending.values()) abort()
      pending.clear()
      for (const t of timeouts) clearTimeout(t)
      timeouts.clear()
    }
  }, [])

  const update = useCallback((id: number, fields: Partial<UploadJob>) => {
    if (!alive.current) return
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, ...fields } : j)))
  }, [])

  const dismiss = useCallback((id: number) => {
    if (!alive.current) return
    setJobs((js) => js.filter((j) => j.id !== id))
  }, [])

  const cancel = useCallback(
    (id: number) => {
      const abort = aborts.current.get(id)
      aborts.current.delete(id)
      abort?.()
      dismiss(id)
    },
    [dismiss],
  )

  const addFiles = useCallback(
    (files: File[], at: Point | undefined, origin: UploadOrigin) => {
      const { valid, rejected } = partitionFiles(files)
      const id = nextId++
      const label = valid.length === 1 ? valid[0].name : `${valid.length} files`
      if (valid.length === 0) {
        if (!alive.current) return
        setJobs((js) => [...js, { id, label: 'Nothing uploaded', progress: 0, state: 'failed', errors: rejected }])
        return
      }
      setJobs((js) => [...js, { id, label, progress: 0, state: 'uploading', errors: rejected }])
      const up = uploadFiles(boardId, valid, {
        at,
        origin,
        onProgress: (p) => update(id, { progress: p }),
      })
      aborts.current.set(id, up.abort)
      up.promise
        .then((results) => {
          if (!alive.current || !aborts.current.delete(id)) return // unmounted or cancelled
          upsertItems(qc, boardId, results.flatMap((r) => (r.ok && r.item ? [r.item] : [])))
          const serverErrors = results
            .filter((r) => !r.ok)
            .map((r) => ({ filename: r.filename, message: `${r.filename}: ${r.error?.message ?? 'failed'}` }))
          const errors = [...rejected, ...serverErrors]
          update(id, { progress: 1, state: errors.length === valid.length + rejected.length ? 'failed' : 'done', errors })
          if (errors.length === 0) {
            const t = setTimeout(() => {
              timers.current.delete(t)
              dismiss(id)
            }, AUTO_DISMISS_MS)
            timers.current.add(t)
          }
        })
        .catch((e: unknown) => {
          if (!alive.current || !aborts.current.delete(id)) return
          const message = e instanceof ApiError ? e.message : 'Upload failed'
          update(id, { state: 'failed', errors: [...rejected, { filename: label, message }] })
        })
    },
    [boardId, qc, update, dismiss],
  )

  const addLink = useCallback(
    async (url: string, at?: Point) => {
      try {
        const res = await apiAddLink(boardId, url, at)
        if (alive.current) upsertItems(qc, boardId, [res.item])
      } catch (e) {
        if (alive.current) {
          const message = e instanceof ApiError ? e.message : 'Could not add that link'
          setJobs((js) => [
            ...js,
            { id: nextId++, label: url, progress: 0, state: 'failed', errors: [{ filename: url, message }] },
          ])
        }
        throw e
      }
    },
    [boardId, qc],
  )

  return { jobs, addFiles, addLink, dismiss, cancel }
}

export type AddFlow = ReturnType<typeof useAddFlow>
