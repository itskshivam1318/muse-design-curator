/** Test-only builders for explorations and analyses, shared by the map and living-board tests. */
import type { AnalysisView, Exploration, ExploreOption } from '../api'
import { makeItem } from './fixtures'

export const opt = (id: string, over: Partial<ExploreOption> = {}): ExploreOption => ({
  id, exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: id, description: '', distance: 'near',
  value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null, undocked: false, ...over,
})

export const analysis: AnalysisView = {
  content_type: 'image',
  parse_status: 'completed',
  // a part on the right third: its callout goes to the right of the item
  parts: [{ key: 'hands', label: 'Hands', region_kind: 'box', region: [0.8, 0.4, 0.9, 0.6], mask_url: null, source: 'ai' }],
  dimensions: [
    { key: 'hand_style', label: 'Hand style', type: 'physical', part: 'hands', prompt: null, kind: 'enum', value: 'x', confidence: 1, source: 'ai', status: 'extracted' },
    { key: 'mood', label: 'Mood', type: 'abstract', part: null, prompt: null, kind: 'enum', value: 'x', confidence: 1, source: 'ai', status: 'extracted' },
  ],
}

export const item = makeItem({ id: 'a', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })

export const exp = (id: string, key: string, options: ExploreOption[], itemId = 'a', over: Partial<Exploration> = {}): Exploration => ({
  id, board_id: 'b1', item_id: itemId, key, options, dx: null, dy: null, ...over,
})
