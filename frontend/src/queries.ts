import { useQuery } from '@tanstack/react-query'
import {
  getAttributes,
  getBoard,
  getBoardLens,
  getProfile,
  getRun,
  type Item,
  keys,
  listBoardPlugins,
  listExplorations,
  listFrames,
  listItems,
  listNodes,
  listPacks,
  listPlugins,
} from './api'
import { useDemo } from './demo'
import { seedVisualizing } from './events'

export const useBoard = (id: string) => useQuery({ queryKey: keys.board(id), queryFn: () => getBoard(id) })
export const useItems = (id: string) =>
  useQuery({ queryKey: keys.items(id), queryFn: () => listItems(id).then(seedVisualizing) })
export const useProfile = (id: string) =>
  useQuery({ queryKey: keys.profile(id), queryFn: () => getProfile(id) })
export const useBoardLens = (id: string) =>
  useQuery({ queryKey: keys.lens(id), queryFn: () => getBoardLens(id) })
export const useExplorations = (boardId: string) =>
  useQuery({ queryKey: keys.explorations(boardId), queryFn: () => listExplorations(boardId) })
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

/** Items that belong on the board: staged takes wait in their option's stage until kept. */
export const visibleItems = (items: Item[]): Item[] => items.filter((i) => !i.staged)

/** What the board counts as its items: on the canvas (not staged) and not notes. */
export const countedItems = (items: Item[]): Item[] => visibleItems(items).filter((i) => i.kind !== 'note')

/**
 * Plugin queries only run when the server has plugins on (plugin endpoints 404 otherwise), so a
 * board without them never lands in an error state.
 */
export function usePlugins() {
  const { pluginsEnabled } = useDemo()
  return useQuery({ queryKey: keys.plugins(), queryFn: listPlugins, enabled: pluginsEnabled })
}
export function usePacks() {
  const { pluginsEnabled } = useDemo()
  return useQuery({ queryKey: keys.packs(), queryFn: listPacks, enabled: pluginsEnabled })
}
export function useBoardPlugins(boardId: string) {
  const { pluginsEnabled } = useDemo()
  return useQuery({
    queryKey: keys.boardPlugins(boardId),
    queryFn: () => listBoardPlugins(boardId),
    enabled: pluginsEnabled,
  })
}
export function useNodes(boardId: string) {
  const { pluginsEnabled } = useDemo()
  return useQuery({ queryKey: keys.nodes(boardId), queryFn: () => listNodes(boardId), enabled: pluginsEnabled })
}

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
