import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
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

let nextId = 1

/** Upload / link ingest with client-side validation, XHR progress and per-file errors. */
export function useAddFlow(boardId: string) {
  const qc = useQueryClient()
  const [jobs, setJobs] = useState<UploadJob[]>([])

  const update = useCallback((id: number, fields: Partial<UploadJob>) => {
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, ...fields } : j)))
  }, [])

  const dismiss = useCallback((id: number) => setJobs((js) => js.filter((j) => j.id !== id)), [])

  const addFiles = useCallback(
    (files: File[], at: Point | undefined, origin: UploadOrigin) => {
      const { valid, rejected } = partitionFiles(files)
      const id = nextId++
      const label = valid.length === 1 ? valid[0].name : `${valid.length} files`
      if (valid.length === 0) {
        setJobs((js) => [...js, { id, label: 'Nothing uploaded', progress: 0, state: 'failed', errors: rejected }])
        return
      }
      setJobs((js) => [...js, { id, label, progress: 0, state: 'uploading', errors: rejected }])
      const up = uploadFiles(boardId, valid, {
        at,
        origin,
        onProgress: (p) => update(id, { progress: p }),
      })
      up.promise
        .then((results) => {
          upsertItems(qc, boardId, results.flatMap((r) => (r.ok && r.item ? [r.item] : [])))
          const serverErrors = results
            .filter((r) => !r.ok)
            .map((r) => ({ filename: r.filename, message: `${r.filename}: ${r.error?.message ?? 'failed'}` }))
          const errors = [...rejected, ...serverErrors]
          update(id, { progress: 1, state: errors.length === valid.length + rejected.length ? 'failed' : 'done', errors })
          if (errors.length === 0) setTimeout(() => dismiss(id), 2500)
        })
        .catch((e: unknown) => {
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
        upsertItems(qc, boardId, [res.item])
      } catch (e) {
        const message = e instanceof ApiError ? e.message : 'Could not add that link'
        setJobs((js) => [
          ...js,
          { id: nextId++, label: url, progress: 0, state: 'failed', errors: [{ filename: url, message }] },
        ])
        throw e
      }
    },
    [boardId, qc],
  )

  return { jobs, addFiles, addLink, dismiss }
}

export type AddFlow = ReturnType<typeof useAddFlow>
