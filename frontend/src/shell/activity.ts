/** The agent card's feed: board events (server, SSE) and the person's own actions (UI log), in time order. */
import { type ActivityEntry, useBoardActivity } from '../events'
import { useUiActivity } from '../telemetry'

/** Both streams merged by `at`, oldest first (ties keep server events first). */
export function mergeActivity(server: readonly ActivityEntry[], ui: readonly ActivityEntry[]): ActivityEntry[] {
  return [...server, ...ui].sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))
}

export function useActivity(): ActivityEntry[] {
  return mergeActivity(useBoardActivity(), useUiActivity())
}
