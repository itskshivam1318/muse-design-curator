import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { UploadResult } from '../api'
import { UploadStatus } from '../panels/UploadStatus'
import { makeItem } from '../test/fixtures'

const uploads: { resolve: (r: UploadResult[]) => void; reject: (e: unknown) => void; abort: ReturnType<typeof vi.fn> }[] = []

vi.mock('../api', async (orig) => {
  const real = await orig<typeof import('../api')>()
  return {
    ...real,
    uploadFiles: vi.fn(() => {
      let resolve!: (r: UploadResult[]) => void
      let reject!: (e: unknown) => void
      const promise = new Promise<UploadResult[]>((res, rej) => {
        resolve = res
        reject = rej
      })
      const abort = vi.fn(() => reject(new real.ApiError(0, 'ABORTED', 'Upload cancelled')))
      uploads.push({ resolve, reject, abort })
      return { promise, abort }
    }),
  }
})
vi.mock('../events', async (orig) => ({ ...(await orig<typeof import('../events')>()), upsertItems: vi.fn() }))

const { useAddFlow } = await import('./useAddFlow')
const { upsertItems } = await import('../events')

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}
const png = () => new File(['x'], 'a.png', { type: 'image/png' })

beforeEach(() => {
  uploads.length = 0
  vi.mocked(upsertItems).mockClear()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('useAddFlow upload lifecycle', () => {
  it('unmounting during an upload aborts it and does not touch state afterwards', async () => {
    const errorSpy = vi.spyOn(console, 'error')
    const { result, unmount } = renderHook(() => useAddFlow('b'), { wrapper })
    act(() => result.current.addFiles([png()], { x: 0, y: 0 }, 'drop'))
    expect(result.current.jobs).toHaveLength(1)
    unmount()
    expect(uploads[0].abort).toHaveBeenCalledTimes(1)
    // a late success after unmount is ignored
    uploads[0].resolve([{ filename: 'a.png', ok: true, item: makeItem() }])
    await new Promise((r) => setTimeout(r, 0))
    expect(upsertItems).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
  })

  it('Cancel aborts the upload and removes the job', async () => {
    const { result } = renderHook(() => useAddFlow('b'), { wrapper })
    act(() => result.current.addFiles([png()], undefined, 'upload'))
    const id = result.current.jobs[0].id
    act(() => result.current.cancel(id))
    expect(uploads[0].abort).toHaveBeenCalledTimes(1)
    expect(result.current.jobs).toEqual([])
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(result.current.jobs).toEqual([]) // the abort rejection does not resurrect it as "failed"
  })

  it('clears the auto-dismiss timer on unmount', async () => {
    vi.useFakeTimers()
    try {
      const { result, unmount } = renderHook(() => useAddFlow('b'), { wrapper })
      act(() => result.current.addFiles([png()], undefined, 'upload'))
      await act(async () => {
        uploads[0].resolve([{ filename: 'a.png', ok: true, item: makeItem() }])
      })
      expect(result.current.jobs[0].state).toBe('done')
      expect(vi.getTimerCount()).toBe(1)
      unmount()
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('UploadStatus', () => {
  it('shows Cancel while uploading and calls onCancel', () => {
    const onCancel = vi.fn()
    render(
      <UploadStatus
        jobs={[{ id: 7, label: 'a.png', progress: 0.4, state: 'uploading', errors: [] }]}
        onDismiss={() => {}}
        onCancel={onCancel}
      />,
    )
    const btn = screen.getByRole('button', { name: 'Cancel uploading a.png' })
    expect(btn.textContent).toBe('Cancel')
    fireEvent.click(btn)
    expect(onCancel).toHaveBeenCalledWith(7)
  })
})
