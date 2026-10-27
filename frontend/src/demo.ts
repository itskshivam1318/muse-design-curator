/** Public-demo state (DEMO_MODE on the server): locked means read-only until unlocked. */
import { useQuery } from '@tanstack/react-query'
import { getDemoStatus, keys } from './api'

export const LOCKED_TITLE = 'Demo — read-only. Unlock to add or edit.'

export function useDemo(): { demoMode: boolean; locked: boolean; exploreEnabled: boolean } {
  const q = useQuery({ queryKey: keys.demo, queryFn: getDemoStatus, staleTime: 60_000, retry: false })
  const demoMode = q.data?.demo_mode === true
  const exploreEnabled = q.data?.explore_enabled !== false
  return { demoMode, locked: demoMode && q.data?.unlocked !== true, exploreEnabled }
}
