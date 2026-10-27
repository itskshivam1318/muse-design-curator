import { createRun, type VariationRequest } from '../api'
import { track } from '../telemetry'
import { runStore } from './runStore'

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `k_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
}

/** POST the run with a fresh Idempotency-Key (one per Run click) and make it the active run. */
export async function startRun(boardId: string, request: VariationRequest): Promise<string> {
  const { run_id } = await createRun(boardId, request, newKey())
  runStore.start({ boardId, runId: run_id, request })
  track('vary.run', {
    itemId: request.source_item_id,
    runId: run_id,
    detail: {
      target: request.target_key,
      mode: request.mode,
      values: request.target_values,
      protected: request.protected_keys,
      nudge: request.nudge,
    },
  })
  return run_id
}

export { newKey as idempotencyKey }
