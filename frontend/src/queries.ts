import { useQuery } from '@tanstack/react-query'
import { getAttributes, getBoard, getBoardLens, getProfile, getRun, keys, listFrames, listItems } from './api'

export const useBoard = (id: string) => useQuery({ queryKey: keys.board(id), queryFn: () => getBoard(id) })
export const useItems = (id: string) => useQuery({ queryKey: keys.items(id), queryFn: () => listItems(id) })
export const useProfile = (id: string) =>
  useQuery({ queryKey: keys.profile(id), queryFn: () => getProfile(id) })
export const useBoardLens = (id: string) =>
  useQuery({ queryKey: keys.lens(id), queryFn: () => getBoardLens(id) })
export const useFrames = (itemId: string | null) =>
  useQuery({
    queryKey: keys.frames(itemId ?? ''),
    queryFn: () => listFrames(itemId ?? ''),
    enabled: itemId !== null,
  })

export const useAttributes = (itemId: string | null) =>
  useQuery({
    queryKey: keys.attributes(itemId ?? ''),
    queryFn: () => getAttributes(itemId ?? ''),
    enabled: itemId !== null,
  })

export const POLL_MS = 1500
/** Safety net while the stream is open, in case a progress event is lost. */
export const SAFETY_POLL_MS = 6000

/**
 * A variation run. While the board's event stream is open, run.progress events invalidate this
 * query (with a slow safety poll); when it is not, poll every 1.5 s. Stop once it completes or fails.
 */
export const useRun = (runId: string | null, streamOpen: boolean) =>
  useQuery({
    queryKey: keys.run(runId ?? ''),
    queryFn: () => getRun(runId ?? ''),
    enabled: runId !== null,
    staleTime: 0,
    refetchInterval: (q) => {
      const status = q.state.data?.run.status
      if (status === 'completed' || status === 'failed') return false
      return streamOpen ? SAFETY_POLL_MS : POLL_MS
    },
  })
