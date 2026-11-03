import type { AgentRun, AgentStep, BoardProfile, Item } from '../api'

export function makeItem(over: Partial<Item> = {}): Item {
  return {
    id: 'item_1', board_id: 'board_1', kind: 'image', origin: 'upload', sha256: 'abc',
    mime: 'image/png', width: 400, height: 300, original_filename: 'a.png', source_url: null,
    page_url: null, page_title: null, creator_handle: null, captured_at: '2026-10-26T00:00:00Z',
    rights_status: 'user_supplied', parse_status: 'completed', parse_error_code: null,
    role: 'reference', x: 10, y: 20, w: 200, h: 150, z: 0,
    storage_path: 'uploads/abc.png', thumb_path: 'thumbs/abc.webp', parent_item_id: null, put_source_item_id: null,
    created_at: '2026-10-26T00:00:00Z',
    explore_option_id: null, generation: null, check: null, note_text: null, staged: false,
    content_type: null, extracted_part: null,
    ...over,
  }
}

export function makeProfile(over: Partial<BoardProfile> = {}): BoardProfile {
  return {
    n_reference: 0, n_counter: 0, attributes: {}, signals: [], tensions: [],
    counter_signals: [], centroid: null, domain_votes: { votes: {}, mixed: false, candidates: null },
    ...over,
  }
}

export const makeStep = (over: Partial<AgentStep> = {}): AgentStep => ({
  id: 's1',
  run_id: 'r1',
  turn: 1,
  tool: 'read_board',
  args: {},
  say: null,
  ok: true,
  result: {},
  item_ids: [],
  highlight: false,
  created_at: '2026-11-03T10:00:00Z',
  ...over,
})

export const makeRun = (over: Partial<AgentRun> = {}): AgentRun => ({
  id: 'r1',
  board_id: 'b1',
  source: 'mcp',
  status: 'running',
  goal: 'Pick a palette',
  deliverables: [],
  output: null,
  finish_refusals: 0,
  note: null,
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
  ...over,
})
