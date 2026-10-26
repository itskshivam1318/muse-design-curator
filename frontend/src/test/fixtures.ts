import type { BoardProfile, Item } from '../api'

export function makeItem(over: Partial<Item> = {}): Item {
  return {
    id: 'item_1', board_id: 'board_1', kind: 'image', origin: 'upload', sha256: 'abc',
    mime: 'image/png', width: 400, height: 300, original_filename: 'a.png', source_url: null,
    page_url: null, page_title: null, creator_handle: null, captured_at: '2026-10-26T00:00:00Z',
    rights_status: 'user_supplied', parse_status: 'completed', parse_error_code: null,
    role: 'reference', x: 10, y: 20, w: 200, h: 150, z: 0,
    storage_path: 'uploads/abc.png', thumb_path: 'thumbs/abc.webp', parent_item_id: null,
    created_at: '2026-10-26T00:00:00Z',
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
