import { useQuery } from '@tanstack/react-query'
import { getBoard, getBoardLens, getProfile, keys, listFrames, listItems } from './api'

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
