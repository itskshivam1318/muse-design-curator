/** Plugin node rules (params, the settings line, what a node accepts and when it can run) and its cache writes. */
import type { QueryClient } from '@tanstack/react-query'
import {
  createNode,
  deleteNode,
  type Item,
  keys,
  type NodesResponse,
  patchNode,
  type PluginInfo,
  type PluginNode,
  type Point,
} from '../api'
import type { Bounds } from '../canvas/geometry'
import { undoHistory } from '../canvas/history'
import { selectionStore } from '../canvas/selection'

export type FieldType = 'string' | 'enum' | 'integer' | 'boolean' | 'json'

export interface Field {
  key: string
  label: string
  type: FieldType
  options?: string[]
  min?: number
  max?: number
  default?: unknown
  /** Shown only while every listed param has the listed value (manifest `x-show-if`). */
  showIf?: Record<string, unknown>
}

const humanize = (key: string) => {
  const s = key.replace(/[_-]+/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** The node card's fields for a plugin's params JSON schema: simple types, everything else as JSON. */
export function paramFields(schema: Record<string, unknown>): Field[] {
  const props = isObj(schema) && isObj(schema.properties) ? schema.properties : {}
  return Object.entries(props).flatMap(([key, raw]) => {
    if (!isObj(raw)) return []
    const enumValues = Array.isArray(raw.enum) ? raw.enum.map(String) : null
    const type: FieldType = enumValues
      ? 'enum'
      : raw.type === 'string'
        ? 'string'
        : raw.type === 'integer'
          ? 'integer'
          : raw.type === 'boolean'
            ? 'boolean'
            : 'json'
    const field: Field = { key, label: typeof raw.title === 'string' ? raw.title : humanize(key), type }
    if (enumValues) field.options = enumValues
    if (typeof raw.minimum === 'number') field.min = raw.minimum
    if (typeof raw.maximum === 'number') field.max = raw.maximum
    if ('default' in raw) field.default = raw.default
    if (isObj(raw['x-show-if'])) field.showIf = raw['x-show-if']
    return [field]
  })
}

/** A param's value as the run would see it: what the node set, else the schema default. */
export function effective(fields: readonly Field[], params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    const v = f.key in params ? params[f.key] : f.default
    if (v !== undefined) out[f.key] = v
  }
  return out
}

/** The fields to show for these params (`x-show-if` hides the rest). */
export function shownFields(fields: readonly Field[], params: Record<string, unknown>): Field[] {
  const values = effective(fields, params)
  return fields.filter((f) => !f.showIf || Object.entries(f.showIf).every(([k, v]) => values[k] === v))
}

const show = (v: unknown): string => (typeof v === 'string' ? v : v === undefined ? '' : JSON.stringify(v))

/** The one settings line on a node card. */
export function summaryLine(plugin: PluginInfo, params: Record<string, unknown>): string {
  const fields = paramFields(plugin.params)
  const values = effective(fields, params)
  const keysOf = new Set(fields.map((f) => f.key))
  if (keysOf.has('mode') && keysOf.has('part')) {
    if (values.mode === 'whole') return 'Whole image'
    const part = show(values.part).trim()
    return part ? `Change only the ${part}` : 'Change only a part'
  }
  const first = fields.find((f) => values[f.key] !== undefined && values[f.key] !== '')
  return first ? `${first.label} ${show(values[first.key])}` : 'No settings'
}

/** An item a node of this plugin can take as an input. */
export function acceptsItem(plugin: PluginInfo, item: Item): boolean {
  return !item.staged && plugin.inputs.kinds.includes(item.kind)
}

const inputs = (n: number) => (n === 1 ? 'input' : 'inputs')

/** Whether Run is allowed, and if not, why (in plain words). `items` are the board's visible items. */
export function canRun(
  plugin: PluginInfo | undefined,
  node: PluginNode,
  items: ReadonlyMap<string, Item>,
): { ok: boolean; reason?: string } {
  if (!plugin) return { ok: false, reason: 'This plugin is not installed' }
  if (plugin.status !== 'available') return { ok: false, reason: `${plugin.runs_on} not connected` }
  // inputs since removed from the board are skipped (the server does the same); judge what is left
  const live = node.input_item_ids.flatMap((id) => items.get(id) ?? [])
  const unreadable = live.find((i) => !acceptsItem(plugin, i))
  if (unreadable) return { ok: false, reason: `${plugin.name} can't read ${unreadable.kind} items` }
  const { min, max } = plugin.inputs
  if (live.length < min) {
    const need = min - live.length
    return { ok: false, reason: live.length === 0 && need === 1 ? 'Add an input' : `Add ${need} more ${inputs(need)}` }
  }
  if (live.length > max) return { ok: false, reason: `Use at most ${max} ${inputs(max)}` }
  return { ok: true }
}

/** The canvas box a node card takes (its stored size). */
export const nodeBounds = (n: PluginNode): Bounds => ({ x: n.x, y: n.y, width: n.w, height: n.h })

/** The topmost node under a canvas point. */
export function nodeAt(nodes: readonly PluginNode[], p: Point): PluginNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i]
    if (p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h) return n
  }
  return null
}

/** Default node size (the server's NODE_W/NODE_H), for placing one before it exists. */
export const NODE_W = 300
export const NODE_H = 360
const GAP = 48

/** Where a new node goes: right of what it reads, else centred on `center`. */
export function placeNode(inputs: Bounds | null, center: Point): Point {
  if (inputs) return { x: Math.round(inputs.x + inputs.width + GAP), y: Math.round(inputs.y) }
  return { x: Math.round(center.x - NODE_W / 2), y: Math.round(center.y - NODE_H / 2) }
}

// ---- cache writes ----

function findNode(qc: QueryClient, nodeId: string): { boardId: string; node: PluginNode } | null {
  for (const [key, data] of qc.getQueriesData<NodesResponse>({ queryKey: ['nodes'] })) {
    const node = data?.nodes.find((n) => n.id === nodeId)
    if (node) return { boardId: String(key[1]), node }
  }
  return null
}

function setNode(qc: QueryClient, boardId: string, nodeId: string, fn: (n: PluginNode) => PluginNode | null) {
  qc.setQueryData<NodesResponse>(keys.nodes(boardId), (old) => {
    if (!old) return old
    const nodes = old.nodes.flatMap((n) => {
      if (n.id !== nodeId) return [n]
      const next = fn(n)
      return next ? [next] : []
    })
    return { ...old, nodes }
  })
}

type NodePatch = Partial<Pick<PluginNode, 'x' | 'y' | 'input_item_ids' | 'params'>>

/**
 * Change a node: the cache first, then the server (the server's answer wins; a failure puts the
 * node back and rethrows). With `undoable`, ⌘Z restores the fields it changed.
 */
export async function updateNode(
  qc: QueryClient,
  nodeId: string,
  patch: NodePatch,
  opts: { undoable?: boolean; before?: NodePatch } = {},
) {
  const found = findNode(qc, nodeId)
  if (!found) return
  const { boardId, node } = found
  const before =
    opts.before ?? (Object.fromEntries(Object.keys(patch).map((k) => [k, node[k as keyof NodePatch]])) as NodePatch)
  setNode(qc, boardId, nodeId, (n) => ({ ...n, ...patch }))
  if (opts.undoable) undoHistory.pushRevert(() => void updateNode(qc, nodeId, before).catch(() => {}))
  try {
    const saved = await patchNode(nodeId, patch)
    if (saved) setNode(qc, boardId, nodeId, (n) => ({ ...n, ...saved }))
  } catch (e) {
    setNode(qc, boardId, nodeId, (n) => ({ ...n, ...before }))
    throw e
  }
}

/** Move a node in the cache only (while its card is dragged); updateNode saves the drop. */
export function previewNode(qc: QueryClient, nodeId: string, at: Point): void {
  const found = findNode(qc, nodeId)
  if (found) setNode(qc, found.boardId, nodeId, (n) => ({ ...n, x: at.x, y: at.y }))
}

const boardItems = (qc: QueryClient, boardId: string) => qc.getQueryData<Item[]>(keys.items(boardId)) ?? []
const pluginOf = (qc: QueryClient, id: string) => qc.getQueryData<PluginInfo[]>(keys.plugins())?.find((p) => p.id === id)

export interface AddResult {
  added: number
  /** Why some or all of the items were not added, in plain words; null when all went in. */
  notice: string | null
}

/**
 * Add items to a node's inputs; ⌘Z takes them off again. Skipped: items not on the board (or not in
 * the cache), ones already in, kinds the plugin cannot read, and any past the plugin's max inputs.
 * Nothing is added while the plugin itself is unknown.
 */
export async function addToNode(qc: QueryClient, nodeId: string, itemIds: readonly string[]): Promise<AddResult> {
  const found = findNode(qc, nodeId)
  if (!found) return { added: 0, notice: null }
  const { boardId, node } = found
  const plugin = pluginOf(qc, node.plugin_id)
  if (!plugin) return { added: 0, notice: 'This plugin is not loaded yet' }
  const byId = new Map(boardItems(qc, boardId).filter((i) => !i.staged).map((i) => [i.id, i]))
  let already = 0
  const unreadable = new Set<string>()
  const fresh: string[] = []
  for (const id of new Set(itemIds)) {
    const item = byId.get(id)
    if (!item) continue
    if (node.input_item_ids.includes(id)) already++
    else if (!acceptsItem(plugin, item)) unreadable.add(item.kind)
    else fresh.push(id)
  }
  const live = node.input_item_ids.filter((id) => byId.has(id)).length
  const room = Math.max(0, plugin.inputs.max - live)
  const taken = fresh.slice(0, room)
  const notice =
    taken.length < fresh.length
      ? `${plugin.name} takes at most ${plugin.inputs.max} ${inputs(plugin.inputs.max)}`
      : unreadable.size > 0
        ? `${plugin.name} can't read ${[...unreadable].join(' or ')} items`
        : already > 0 && taken.length === 0
          ? already === 1
            ? 'That item is already an input'
            : 'Those items are already inputs'
          : null
  if (taken.length > 0)
    await updateNode(qc, nodeId, { input_item_ids: [...node.input_item_ids, ...taken] }, { undoable: true })
  return { added: taken.length, notice }
}

/** Remove a node from the board. */
export async function removeNode(qc: QueryClient, nodeId: string): Promise<void> {
  const found = findNode(qc, nodeId)
  if (!found) return
  setNode(qc, found.boardId, nodeId, () => null)
  try {
    await deleteNode(nodeId)
  } catch (e) {
    void qc.invalidateQueries({ queryKey: keys.nodes(found.boardId) })
    throw e
  }
}

function cacheNode(qc: QueryClient, boardId: string, node: PluginNode) {
  qc.setQueryData<NodesResponse>(keys.nodes(boardId), (old) => {
    const base = old ?? { nodes: [], runs: {} }
    return { ...base, nodes: [...base.nodes.filter((n) => n.id !== node.id), node] }
  })
}

/** Make a node of `plugin` at `at` with the given items (those it reads, up to its max) as inputs. */
export async function createNodeWith(
  qc: QueryClient,
  boardId: string,
  plugin: PluginInfo,
  at: Point,
  itemIds: readonly string[],
): Promise<PluginNode> {
  const byId = new Map(boardItems(qc, boardId).map((i) => [i.id, i]))
  const input_item_ids = itemIds
    .filter((id) => {
      const item = byId.get(id)
      return !!item && acceptsItem(plugin, item)
    })
    .slice(0, plugin.inputs.max)
  const node = await createNode(boardId, { plugin_id: plugin.id, x: Math.round(at.x), y: Math.round(at.y), input_item_ids })
  cacheNode(qc, boardId, node)
  return node
}

/** A node of `plugin` with the current selection as its inputs. */
export function createNodeFromSelection(qc: QueryClient, boardId: string, plugin: PluginInfo, at: Point): Promise<PluginNode> {
  return createNodeWith(qc, boardId, plugin, at, selectionStore.get().selected)
}
