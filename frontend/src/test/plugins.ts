import type { PluginInfo, PluginNode, PluginRun } from '../api'

export const IMAGE_PARAMS = {
  type: 'object',
  properties: {
    mode: { type: 'string', enum: ['part', 'whole'], default: 'part' },
    part: { type: 'string', default: '', 'x-show-if': { mode: 'part' } },
    prompt: { type: 'string' },
    count: { type: 'integer', minimum: 1, maximum: 4, default: 1 },
  },
}

export function makePlugin(over: Partial<PluginInfo> = {}): PluginInfo {
  return {
    id: 'image', name: 'Image', description: 'Masked edits and new images from items and notes.',
    mark: 'IMG', tint: '#dfe5f6', ink: '#2a4aae', runner: 'model', runs_on: 'Muse Spark',
    inputs: { kinds: ['image', 'note'], min: 1, max: 12 }, params: IMAGE_PARAMS, outputs: ['images'],
    secondary: 'Prompt', status: 'available', builtin: true,
    ...over,
  }
}

export function makeNode(over: Partial<PluginNode> = {}): PluginNode {
  return {
    id: 'node1', board_id: 'b1', plugin_id: 'image', x: 400, y: 0, w: 300, h: 360,
    input_item_ids: [], params: {}, last_run_id: null,
    ...over,
  }
}

export function makePluginRun(over: Partial<PluginRun> = {}): PluginRun {
  return {
    id: 'run1', node_id: 'node1', plugin_id: 'image', status: 'queued', progress: null, output: null,
    error_code: null, error_message: null, created_at: '2026-10-29T00:00:00Z', finished_at: null,
    ...over,
  }
}
