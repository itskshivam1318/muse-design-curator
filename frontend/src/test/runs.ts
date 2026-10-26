import type { CandidateView, RunResponse } from '../api'

export function cand(id: string, state: CandidateView['state'], over: Partial<CandidateView> = {}): CandidateView {
  return {
    id, corpus_item_id: `cx_${id}`, image_url: `/api/corpus/cx_${id}/image`, width: 400, height: 500,
    provenance: { credit: 'Photo by A', landing_url: 'https://example.org/p', license_code: 'CC-BY-4.0', creator_name: 'A' },
    state, rank: state === 'validated' ? 1 : null, scores: null, checks: [], observed_target_value: 'navy',
    decision: null, decisions: [], ...over,
  }
}

export function runResponse(over: Partial<RunResponse> = {}): RunResponse {
  return {
    run: {
      id: 'r1', board_id: 'b1', source_item_id: 'i1', lens_id: 'l1', target_key: 'dial_color', mode: 'explore',
      target_values: [], nudge: null, protected_keys: [], status: 'completed', error_code: null,
      created_at: '', completed_at: '',
    },
    progress: { stage: 'completed', validated_n: 4, shortlist_n: 4 },
    summary: {
      pool_size: 10, excluded: {}, validated: 2, uncertain: 1, rejected: 1, returned: 2,
      shortfall: [
        { code: 'protected_changed', count: 5, message: '5 changed a protected attribute (Case finish)' },
        { code: 'uncertain', count: 1, message: '1 had uncertain Dial colour — under Needs review' },
      ],
    },
    results: [cand('c1', 'validated'), cand('c2', 'validated')],
    needs_review: [cand('c3', 'uncertain')],
    rejected: [],
    excluded_counts: {},
    ...over,
  }
}
