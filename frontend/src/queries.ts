import { useQuery } from '@tanstack/react-query'
import {
  getAnalysis,
  getAttributes,
  getBoardContext,
  getRegion,
  getRenderers,
  getBoard,
  getBoardLens,
  getProfile,
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
export const useBoardContext = (boardId: string) =>
  useQuery({ queryKey: keys.boardContext(boardId), queryFn: () => getBoardContext(boardId) })
/** An item's parts and dimensions; refetched on the item.analysed event. */
export const useAnalysis = (itemId: string | null) =>
  useQuery({
    queryKey: keys.analysis(itemId ?? ''),
    queryFn: () => getAnalysis(itemId ?? ''),
    enabled: itemId !== null,
  })
export const useRegion = (itemId: string, partKey: string, enabled = true) =>
  useQuery({ queryKey: keys.region(itemId, partKey), queryFn: () => getRegion(itemId, partKey), enabled })
export const useRenderers = (itemId: string, key: string, enabled = true) =>
  useQuery({ queryKey: keys.renderers(itemId, key), queryFn: () => getRenderers(itemId, key), enabled })
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
