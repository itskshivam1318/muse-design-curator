/**
 * Typed client for the FastAPI backend (everything under /api). In dev Vite proxies /api; a deployed
 * frontend whose API lives on another origin sets VITE_API_URL (e.g. https://user-dle.hf.space).
 */

export type ParseStatus = 'pending' | 'pending_lens' | 'processing' | 'completed' | 'failed'
export type ItemKind = 'image' | 'video' | 'link' | 'note' | 'model'
export type ItemRole = 'reference' | 'counter_example'

export interface Item {
  id: string
  board_id: string
  kind: ItemKind
  origin: string
  sha256: string | null
  mime: string | null
  width: number | null
  height: number | null
  original_filename: string | null
  source_url: string | null
  page_url: string | null
  page_title: string | null
  creator_handle: string | null
  captured_at: string
  rights_status: 'user_supplied' | 'licensed' | 'generated'
  parse_status: ParseStatus
  parse_error_code: string | null
  role: ItemRole
  x: number
  y: number
  w: number
  h: number
  z: number
  storage_path: string | null
  thumb_path: string | null
  parent_item_id: string | null
  put_source_item_id: string | null
  option_run_id: string | null
  created_at: string
  /** Stored provenance of a licensed (corpus) image; null for the user's own items. */
  licence?: ItemLicence | null
  /** Set on an image generated from an explore option. */
  explore_option_id: string | null
  /**
   * Generation provenance. On a note it can instead hold `{ visualizing_since }` (the visualize
   * claim): never read a non-null `generation` as "generated"; that is `origin === 'generated'`.
   */
  generation: {
    model?: string
    prompt?: string
    option_id?: string
    visualizing_since?: string
    plugin?: string
    run_id?: string
    /** On a rewritten note: where the new passage sits in its text. */
    changed_range?: [number, number]
  } | null
  check: GeneratedCheck | null
  /** The text of a note card; null on every other kind. */
  note_text: string | null
  /** A staged item is a take or plugin result not yet kept on the board. */
  staged: boolean
  /** Client only: a written version of a note waiting on the board to be kept or removed. */
  pending?: boolean
  /** What the item is (set by analysis or the person); null until known. */
  content_type: ContentType | null
  /** The part key this item was extracted from its parent as; null otherwise. */
  extracted_part: string | null
}

export type ContentType = 'image' | 'ui' | 'text'
export type RegionKind = 'mask' | 'box' | 'text_range'

/** Where a part lives: a box [x0, y0, x1, y1] as fractions, a text range [start, end], or a mask image (with its bbox). */
export interface Region {
  kind: RegionKind
  box?: number[]
  range?: number[]
  mask_url?: string
}

export interface PartView {
  key: string
  label: string
  region_kind: RegionKind
  /** The stored region: box [x0,y0,x1,y1] in 0..1, text_range [start,end], null for an un-located mask. */
  region: number[] | null
  mask_url: string | null
  source: string
}

export interface DimensionView {
  key: string
  label: string
  type: 'physical' | 'abstract'
  part: string | null
  prompt: string | null
  kind: AttrKind
  value: string | number | boolean | null
  confidence: number | null
  source: string
  /** "stale" when the value predates an edit to the item. */
  status: string
}

export interface AnalysisView {
  content_type: ContentType | null
  parse_status: ParseStatus
  parts: PartView[]
  dimensions: DimensionView[]
}

export interface RendererInfo {
  id: string
  title: string
  detail: string
  builtin: boolean
}

export interface Offer {
  label: string
  dim_type: 'physical' | 'abstract'
  kind: AttrKind
  part: string | null
  count: number
  total: number
}

export type OfferBody = Pick<Offer, 'label' | 'dim_type' | 'kind' | 'part'>

export interface BoardContextView {
  your_words: string
  learned: string[]
  offers: Offer[]
}

/** Generated means origin, never a non-null `generation` (a note holds its visualize claim there). */
export const isGenerated = (item: Item): boolean => item.origin === 'generated'

/** The comparator's verdict on a generated image: did the target land, what was kept. */
export interface GeneratedCheck {
  target?: {
    answer: 'yes' | 'no' | 'unclear'
    confidence: number
    box?: number[] | null
    note: string
  }
  kept?: number
  of?: number
  drifted?: string[]
  unknown?: number
  error?: string
}

export type Distance = 'near' | 'bold' | 'wild'

export interface ExploreOption {
  id: string
  exploration_id: string
  parent_option_id: string | null
  batch: number
  steer: string | null
  name: string
  description: string
  distance: Distance
  value: string | number | boolean | null
  keeps: string[]
  edit_prompt?: string
  status: 'open' | 'dismissed' | 'visualizing' | 'visualized' | 'kept'
  last_error: string | null
  x: number | null
  y: number | null
  created_at?: string
  /** The take that was kept onto the board, if any. */
  kept_item_id: string | null
  /** Item ids of the staged takes generated for this option. */
  takes: string[]
  /** The kept take was dragged out of its ring: it is an ordinary board item. */
  undocked: boolean
}

export interface Exploration {
  id: string
  board_id: string
  item_id: string
  key: string
  created_at?: string
  options: ExploreOption[]
  /** The hub's stored offset from its source item's centre; null until the hub is placed. */
  dx: number | null
  dy: number | null
}

export interface ItemLicence {
  credit: string
  license_code: string
  license_url: string | null
  creator_name: string | null
  landing_url: string | null
  source: string
}

export interface PluginInfo {
  id: string
  name: string
  description: string
  mark: string
  tint: string
  ink: string
  runner: 'python' | 'llm' | 'model'
  runs_on: string
  inputs: { kinds: string[]; min: number; max: number }
  /** JSON schema of the plugin's params. */
  params: Record<string, unknown>
  outputs: string[]
  secondary: string | null
  status: 'available' | 'not_connected'
  builtin: boolean
}

export interface PluginPack {
  id: string
  name: string
  about: string
  plugin_ids: string[]
}

export interface PluginNode {
  id: string
  board_id: string
  plugin_id: string
  x: number
  y: number
  w: number
  h: number
  input_item_ids: string[]
  params: Record<string, unknown>
  last_run_id: string | null
}

export type PluginRunStatus = 'queued' | 'running' | 'done' | 'failed'

export interface PluginRun {
  id: string
  node_id: string
  plugin_id: string
  status: PluginRunStatus
  progress: { message: string } | null
  output: {
    text?: unknown
    table?: unknown
    created_item_ids?: string[]
    skipped_attributes?: unknown[]
  } | null
  error_code: string | null
  error_message: string | null
  created_at: string
  finished_at: string | null
}

export interface NodesResponse {
  nodes: PluginNode[]
  /** The latest run of each node, by node id. */
  runs: Record<string, PluginRun>
}

export type AgentSource = 'mcp' | 'muse'
export type AgentRunStatus = 'running' | 'needs_input' | 'waiting' | 'done' | 'paused'

export interface AgentOutput {
  title: string
  sections: { deliverable: string; items: { item_id: string; why: string }[] }[]
  note_ids: string[]
}

/** One agent working on a board toward a goal (from Muse Code over MCP, or Muse's own). */
export interface AgentRun {
  id: string
  board_id: string
  source: AgentSource
  status: AgentRunStatus
  goal: string
  deliverables: string[]
  output: AgentOutput | null
  finish_refusals: number
  note: string | null
  created_at: string
  updated_at: string
}

/** One tool call of an agent run; `ok` false is a refused call. */
export interface AgentStep {
  id: string
  run_id: string
  turn: number
  tool: string
  args: Record<string, unknown>
  say: string | null
  ok: boolean
  result: Record<string, unknown>
  item_ids: string[]
  highlight: boolean
  created_at: string
}

export interface AgentRunWithSteps extends AgentRun {
  /** In turn order. */
  steps: AgentStep[]
}

export interface AgentAnswer {
  call_id: string
  text?: string
  choice?: string
  box?: number[]
}

export interface AgentMessageData {
  selection?: string[]
  call_id?: string
  tool?: 'ask_user' | 'confirm_part'
  args?: Record<string, unknown>
  region?: { kind: string; box: number[] | null; mask_url: string | null } | null
  answer?: AgentAnswer
  /** Internal bookkeeping; the UI ignores it. */
  consumed?: boolean
}

/** One line of a chat with the board agent: what the person said, what it said, or a question it asked. */
export interface AgentMessage {
  id: string
  run_id: string
  role: 'person' | 'agent' | 'question'
  text: string
  data: AgentMessageData | null
  answered: boolean
  created_at: string
}

export interface Board {
  id: string
  title: string
  context: string
  domain: string | null
  lens_id: string | null
  created_at: string
  updated_at: string
}

export interface BoardSummary {
  id: string
  title: string
  updated_at: string
}

export interface ColorCluster {
  hex: string
  name: string
  count: number
  share: number
}

export interface AttributeProfile {
  key: string
  label: string
  kind: string
  n_known: number
  distribution: Record<string, number>
  modal_value: string | null
  consistency: number | null
  median: number | null
  iqr: number | null
  clusters: ColorCluster[]
  medoid_item_id: string | null
  values: string[]
}

export interface Signal {
  key: string
  label: string
  kind: string
  modal_value: string | null
  consistency: number
  n_known: number
}

export interface Tension {
  key: string
  label: string
  values: string[]
  shares: number[]
}

export interface CounterSignal {
  key: string
  label: string
  value: string
  counter_count: number
  reference_count: number
}

export interface BoardProfile {
  n_reference: number
  n_counter: number
  attributes: Record<string, AttributeProfile>
  signals: Signal[]
  tensions: Tension[]
  counter_signals: CounterSignal[]
  centroid: number[] | null
  domain_votes: { votes: Record<string, number>; mixed: boolean; candidates: string[] | null }
}

export interface ProfileSnapshot {
  version: number
  profile: BoardProfile
  computed_at?: string
}

export interface PartSpec {
  id: string
  sam_prompt: string
  grounding: 'sam' | 'whole_image'
}

export interface AttributeSpec {
  key: string
  label: string
  category: string
  kind: string
  part?: string | null
  [extra: string]: unknown
}

export interface LensSpec {
  id: string
  domain: string
  label: string
  origin: 'curated' | 'proposed' | 'edited'
  parts: PartSpec[]
  attributes: AttributeSpec[]
  notes: string[]
}

export interface LensRow {
  id: string
  board_id: string | null
  domain: string
  version: number
  origin: string
  status: 'proposed' | 'confirmed'
  spec: LensSpec
  created_at: string
}

export type AttrKind = 'enum' | 'ordinal' | 'number' | 'boolean' | 'color' | 'text' | 'shape'
export type AttrValue = string | number | boolean | null
export type AttrStatus = 'extracted' | 'uncertain' | 'missing' | 'edited' | 'confirmed'

/** One attribute record on a board item (GET /items/{id}/attributes). */
export interface ItemAttribute {
  key: string
  label: string
  category: string
  kind: AttrKind
  part: string | null
  value: AttrValue
  confidence: number
  status: AttrStatus
  source: string
  source_detail?: string
  evidence?: { kind: string; bbox?: number[] | null; note?: string | null } | null
  enabled: boolean
  measured?: Record<string, unknown> | null
  updated_at?: string
}

export interface ItemAttributes {
  parse_status: ParseStatus
  parse_error_code: string | null
  lens: LensSpec | null
  provider: { id: string; model: string | null; is_mock: boolean }
  attributes: ItemAttribute[]
}

export interface AttributeEvent {
  id: string
  key: string
  actor: string
  action: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  created_at: string
}

export interface Frame {
  id: string
  t_ms: number
  chosen: boolean
}

export interface UploadResult {
  filename: string
  ok: boolean
  deduped?: boolean
  item?: Item
  error?: { code: string; message: string }
}

export interface Point {
  x: number
  y: number
}

export type UploadOrigin = 'upload' | 'drop' | 'paste'

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface DemoStatus {
  demo_mode: boolean
  unlocked: boolean
  /** Absent on the unlock response. */
  explore_enabled?: boolean
  plugins_enabled?: boolean
}

export const keys = {
  demo: ['demo'] as const,
  boards: ['boards'] as const,
  board: (id: string) => ['board', id] as const,
  items: (id: string) => ['items', id] as const,
  profile: (id: string) => ['profile', id] as const,
  lens: (id: string) => ['lens', id] as const,
  frames: (itemId: string) => ['frames', itemId] as const,
  run: (runId: string) => ['run', runId] as const,
  explorations: (boardId: string) => ['explorations', boardId] as const,
  attributes: (itemId: string) => ['attributes', itemId] as const,
  plugins: () => ['plugins'] as const,
  packs: () => ['plugin-packs'] as const,
  boardPlugins: (id: string) => ['boardPlugins', id] as const,
  nodes: (id: string) => ['nodes', id] as const,
  analysis: (itemId: string) => ['analysis', itemId] as const,
  region: (itemId: string, partKey: string) => ['region', itemId, partKey] as const,
  renderers: (itemId: string, key: string) => ['renderers', itemId, key] as const,
  boardContext: (boardId: string) => ['boardContext', boardId] as const,
  attributeHistory: (itemId: string, key: string) => ['attributeHistory', itemId, key] as const,
  agentRuns: (boardId: string) => ['agentRuns', boardId] as const,
  agentRun: (runId: string) => ['agentRun', runId] as const,
  agentMessages: (runId: string) => ['agentMessages', runId] as const,
  chatStatus: () => ['chatStatus'] as const,
}

/** The API origin with no trailing slash; empty means same origin (the dev proxy). */
export const API_ORIGIN = apiOrigin(import.meta.env.VITE_API_URL)

export function apiOrigin(raw: string | undefined): string {
  return (raw ?? '').trim().replace(/\/+$/, '')
}

const BASE = `${API_ORIGIN}/api`

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json()
    if (body?.error) return new ApiError(res.status, body.error.code, body.error.message, body.error.details)
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, 'HTTP_ERROR', `Request failed (${res.status})`)
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const headers = new Headers(rest.headers)
  if (json !== undefined) headers.set('Content-Type', 'application/json')
  const res = await fetch(BASE + path, {
    ...rest,
    headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!res.ok) throw await toError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const listBoards = () =>
  request<{ boards: BoardSummary[] }>('/boards').then((r) => r.boards)
export const createBoard = (body: { title: string; context?: string; domain?: string | null }) =>
  request<Board>('/boards', { method: 'POST', json: body })
export const getBoard = (id: string) => request<Board>(`/boards/${enc(id)}`)
export const patchBoard = (
  id: string,
  body: Partial<Pick<Board, 'title' | 'context' | 'domain'>>,
) => request<Board>(`/boards/${enc(id)}`, { method: 'PATCH', json: body })
export const listItems = (boardId: string) =>
  request<{ items: Item[] }>(`/boards/${enc(boardId)}/items`).then((r) => r.items)
export const getProfile = (boardId: string) =>
  request<ProfileSnapshot>(`/boards/${enc(boardId)}/profile`)

export const addLink = (boardId: string, url: string, at?: Point) =>
  request<{ item: Item; deduped: boolean }>(`/boards/${enc(boardId)}/items`, {
    method: 'POST',
    json: { url, ...(at ? { x: at.x, y: at.y } : {}) },
  })

export const patchItem = (
  id: string,
  body: Partial<Pick<Item, 'x' | 'y' | 'w' | 'h' | 'z' | 'role' | 'note_text' | 'content_type'>> & { chosen_frame_id?: string },
) => request<Item>(`/items/${enc(id)}`, { method: 'PATCH', json: body })
export const deleteItem = (id: string) => request<void>(`/items/${enc(id)}`, { method: 'DELETE' })
/** Keep a plugin option: it stops being an option and is an ordinary item. */
export const keepOption = (id: string) => request<Item>(`/items/${enc(id)}/keep-option`, { method: 'POST' })
/** Remove every option still standing from a node's runs. */
export const clearOptions = (nodeId: string) =>
  request<{ removed_item_ids: string[] }>(`/nodes/${enc(nodeId)}/clear-options`, { method: 'POST' })
/** Bring a removed item back (undo of a removal); an option stays flagged as one. */
export const restoreItem = (id: string) => request<Item>(`/items/${enc(id)}/restore`, { method: 'POST' })
export const listFrames = (itemId: string) =>
  request<{ frames: Frame[] }>(`/items/${enc(itemId)}/frames`).then((r) => r.frames)

/** The board's current lens, or its newest proposal; null when it has none yet. */
export const getBoardLens = (boardId: string) =>
  request<{ lens: LensRow | null }>(`/boards/${enc(boardId)}/lens`).then((r) => r.lens)
export const getDemoStatus = () => request<DemoStatus>('/demo/status')
/** Sets the HttpOnly unlock cookie on success; 401 for a wrong passcode, 429 after too many. */
export const unlockDemo = (passcode: string) =>
  request<DemoStatus>('/demo/unlock', { method: 'POST', json: { passcode } })

export const exploreItem = (
  itemId: string,
  body: { key: string; steer?: string; parent_option_id?: string; mode?: 'initial' | 'more' | 'further' },
) => request<Exploration>(`/items/${enc(itemId)}/explore`, { method: 'POST', json: body })
export const listExplorations = (boardId: string) =>
  request<{ explorations: Exploration[] }>(`/boards/${enc(boardId)}/explorations`).then((r) => r.explorations)
export const patchOption = (
  optionId: string,
  body: { status?: 'dismissed' | 'open'; x?: number; y?: number; undocked?: boolean },
) => request<ExploreOption>(`/options/${enc(optionId)}`, { method: 'PATCH', json: body })
/** A flower hub's offset from its source item's centre; nulls put it back in its automatic slot. */
export const patchExploration = (explorationId: string, body: { dx: number | null; dy: number | null }) =>
  request<Exploration>(`/explorations/${enc(explorationId)}`, { method: 'PATCH', json: body })
/** `at` is where the canvas draws the option's note; the server saves it and places the image beside it. */
export const visualizeOption = (optionId: string, opts: { at?: Point; renderer_id?: string } = {}) => {
  const json = { ...(opts.at ?? {}), ...(opts.renderer_id ? { renderer_id: opts.renderer_id } : {}) }
  return request<void>(`/options/${enc(optionId)}/visualize`, {
    method: 'POST',
    ...(Object.keys(json).length ? { json } : {}),
  })
}

export const keepTake = (optionId: string, itemId: string, at?: Point, size?: { w: number; h: number }) =>
  request<ExploreOption>(`/options/${enc(optionId)}/keep`, {
    method: 'POST',
    json: { item_id: itemId, ...(at ? { x: at.x, y: at.y } : {}), ...(size ? { w: size.w, h: size.h } : {}) },
  })
export const unkeepTake = (optionId: string) =>
  request<ExploreOption>(`/options/${enc(optionId)}/unkeep`, { method: 'POST' })

export const createNote = (boardId: string, body: { text: string; x: number; y: number; w?: number; h?: number }) =>
  request<Item>(`/boards/${enc(boardId)}/notes`, { method: 'POST', json: body })
export const patchNoteText = (itemId: string, text: string) => patchItem(itemId, { note_text: text })
export const visualizeNote = (itemId: string) =>
  request<{ note_id: string; status: string }>(`/items/${enc(itemId)}/visualize`, { method: 'POST' })

export const listPlugins = () => request<{ plugins: PluginInfo[] }>('/plugins').then((r) => r.plugins)
export const listPacks = () => request<{ packs: PluginPack[] }>('/plugin-packs').then((r) => r.packs)
export const listBoardPlugins = (boardId: string) =>
  request<{ plugin_ids: string[] }>(`/boards/${enc(boardId)}/plugins`).then((r) => r.plugin_ids)
export const addBoardPlugin = (boardId: string, pluginId: string) =>
  request<{ plugin_ids: string[] }>(`/boards/${enc(boardId)}/plugins`, {
    method: 'POST',
    json: { plugin_id: pluginId },
  }).then((r) => r.plugin_ids)
export const removeBoardPlugin = (boardId: string, pluginId: string) =>
  request<void>(`/boards/${enc(boardId)}/plugins/${enc(pluginId)}`, { method: 'DELETE' })
export const listNodes = (boardId: string) => request<NodesResponse>(`/boards/${enc(boardId)}/nodes`)
export const createNode = (
  boardId: string,
  body: { plugin_id: string; x: number; y: number; input_item_ids?: string[] },
) => request<PluginNode>(`/boards/${enc(boardId)}/nodes`, { method: 'POST', json: body })
export const patchNode = (
  nodeId: string,
  body: { x?: number; y?: number; input_item_ids?: string[]; params?: Record<string, unknown> },
) => request<PluginNode>(`/nodes/${enc(nodeId)}`, { method: 'PATCH', json: body })
export const deleteNode = (nodeId: string) => request<void>(`/nodes/${enc(nodeId)}`, { method: 'DELETE' })
/** Describe what the node's inputs show as a prompt (the Describe button on a prompt field). */
export const describeNode = (nodeId: string) =>
  request<{ prompt: string }>(`/nodes/${enc(nodeId)}/describe`, { method: 'POST' })
export const runNode = (nodeId: string) => request<PluginRun>(`/nodes/${enc(nodeId)}/run`, { method: 'POST' })

/** Newest first. */
export const getAgentRuns = (boardId: string) =>
  request<{ runs: AgentRun[] }>(`/boards/${enc(boardId)}/agent-runs`).then((r) => r.runs)
export const getAgentRun = (runId: string) => request<AgentRunWithSteps>(`/agent-runs/${enc(runId)}`)
export const patchAgentRun = (runId: string, body: { status: 'paused' }) =>
  request<AgentRun>(`/agent-runs/${enc(runId)}`, { method: 'PATCH', json: body })

export const getAgentMessages = (runId: string) =>
  request<{ messages: AgentMessage[] }>(`/agent-runs/${enc(runId)}/messages`).then((r) => r.messages)
export const sendAgentMessage = (
  boardId: string,
  body: { text: string; selection: string[]; answer?: AgentAnswer },
) =>
  request<{ run: AgentRun; message: AgentMessage }>(`/boards/${enc(boardId)}/agent/messages`, {
    method: 'POST',
    json: body,
  })
export const newChat = (runId: string) => request<AgentRun>(`/agent-runs/${enc(runId)}/new-chat`, { method: 'POST' })
export const getChatStatus = () => request<{ available: boolean; reason: string | null }>('/agent/chat-status')
export const agentTraceUrl = (runId: string) => `${BASE}/agent-runs/${enc(runId)}/trace`

export const patchAgentStep =(stepId: string, body: { highlight: boolean }) =>
  request<AgentStep>(`/agent-steps/${enc(stepId)}`, { method: 'PATCH', json: body })

export const pairCode = () =>
  request<{ code: string; expires_at: string }>('/extension/pair-code', { method: 'POST' })

export const getAttributes = (itemId: string) => request<ItemAttributes>(`/items/${enc(itemId)}/attributes`)
export const patchAttribute = (
  itemId: string,
  key: string,
  body: { value: AttrValue } | { action: 'confirm' | 'disable' | 'enable' },
) => request<ItemAttribute>(`/items/${enc(itemId)}/attributes/${enc(key)}`, { method: 'PATCH', json: body })
export const getAttributeHistory = (itemId: string, key: string) =>
  request<{ events: AttributeEvent[] }>(`/items/${enc(itemId)}/attributes/${enc(key)}/history`).then((r) => r.events)

/** Short cache-busting token: the thumbnail path changes when a video's chosen frame changes. */
function version(item: Item): string {
  return (item.thumb_path ?? item.storage_path ?? '').replace(/[^a-z0-9]/gi, '').slice(-12)
}

export const itemImageUrl = (item: Item, size: 'thumb' | 'full') =>
  `${BASE}/items/${enc(item.id)}/image?size=${size}&v=${version(item)}`
/** A 3D item's .glb: the media route serves a model's stored file as its full size. */
export const itemModelUrl = (item: Item) => itemImageUrl(item, 'full')
/** A video item's file, for inline playback. */
export const itemVideoUrl = (item: Item) => `${BASE}/items/${enc(item.id)}/video?v=${version(item)}`
/** An item's thumbnail by id alone (no cache-busting token: the caller has no item row). */
export const itemThumbUrl = (itemId: string) => `${BASE}/items/${enc(itemId)}/image?size=thumb`
export const frameImageUrl = (itemId: string, frameId: string) =>
  `${BASE}/items/${enc(itemId)}/frames/${enc(frameId)}/image`

/**
 * Multipart upload through XMLHttpRequest so the UI can show upload progress (fetch cannot).
 * Resolves with per-file results; a batch where every file failed (HTTP 400) still resolves.
 */
export function uploadFiles(
  boardId: string,
  files: File[],
  opts: { at?: Point; origin?: UploadOrigin; onProgress?: (fraction: number) => void } = {},
): { promise: Promise<UploadResult[]>; abort: () => void } {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<UploadResult[]>((resolve, reject) => {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    if (opts.at) {
      form.append('x', String(opts.at.x))
      form.append('y', String(opts.at.y))
    }
    const q = opts.origin === 'drop' ? '?origin=drop' : ''
    xhr.open('POST', `${BASE}/boards/${enc(boardId)}/items${q}`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total)
    }
    xhr.onload = () => {
      const body = xhr.response as { results?: UploadResult[]; error?: { code: string; message: string } } | null
      if (body?.results) resolve(body.results)
      else if (body?.error) reject(new ApiError(xhr.status, body.error.code, body.error.message))
      else reject(new ApiError(xhr.status, 'HTTP_ERROR', `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new ApiError(0, 'NETWORK_ERROR', 'Upload failed: network error'))
    xhr.onabort = () => reject(new ApiError(0, 'ABORTED', 'Upload cancelled'))
    xhr.send(form)
  })
  return { promise, abort: () => xhr.abort() }
}

const item = (itemId: string) => `/items/${enc(itemId)}`

export const getAnalysis = (itemId: string) => request<AnalysisView>(`${item(itemId)}/analysis`)
export const analyseItem = (itemId: string) => request<void>(`${item(itemId)}/analyse`, { method: 'POST' })
export const getRegion = (itemId: string, partKey: string) =>
  request<Region>(`${item(itemId)}/parts/${enc(partKey)}/region`)
export const addPart = (itemId: string, body: { label: string; region?: Region }) =>
  request<PartView>(`${item(itemId)}/parts`, { method: 'POST', json: body })
export const renamePart = (itemId: string, partKey: string, label: string) =>
  request<PartView>(`${item(itemId)}/parts/${enc(partKey)}`, { method: 'PATCH', json: { label } })
export const removePart = (itemId: string, partKey: string) =>
  request<void>(`${item(itemId)}/parts/${enc(partKey)}`, { method: 'DELETE' })
export const addDimension = (
  itemId: string,
  body: { label: string; type: DimensionView['type']; part?: string | null; prompt?: string; kind?: AttrKind },
) => request<DimensionView>(`${item(itemId)}/dimensions`, { method: 'POST', json: body })
export const updateDimension = (
  itemId: string,
  key: string,
  body: Partial<Pick<DimensionView, 'label' | 'prompt' | 'kind' | 'value'>>,
) => request<DimensionView>(`${item(itemId)}/dimensions/${enc(key)}`, { method: 'PATCH', json: body })
export const removeDimension = (itemId: string, key: string) =>
  request<void>(`${item(itemId)}/dimensions/${enc(key)}`, { method: 'DELETE' })
export const setContentType = (itemId: string, contentType: ContentType) =>
  patchItem(itemId, { content_type: contentType })
/** Cut a part out of its item as a new item. */
export const extractPart = (itemId: string, partKey: string) =>
  request<Item>(`${item(itemId)}/parts/${enc(partKey)}/extract`, { method: 'POST' })
export type PutSpot = { part: string } | { point: { fx: number; fy: number } }
/** Put one picture into another at the chosen spots; the new picture arrives by event. */
export const putInto = (targetId: string, body: { source_id: string; spots: PutSpot[]; words?: string }) =>
  request<{ job_id: string; x: number; y: number; w: number; h: number }>(`${item(targetId)}/put-into`, {
    method: 'POST',
    json: body,
  })
export const getRenderers = (itemId: string, key: string) =>
  request<RendererInfo[]>(`${item(itemId)}/dimensions/${enc(key)}/renderers`)

export const getBoardContext = (boardId: string) =>
  request<BoardContextView>(`/boards/${enc(boardId)}/context`)
export const acceptOffer = (boardId: string, body: OfferBody) =>
  request<BoardContextView>(`/boards/${enc(boardId)}/offers/accept`, { method: 'POST', json: body })
export const declineOffer = (boardId: string, body: OfferBody) =>
  request<BoardContextView>(`/boards/${enc(boardId)}/offers/decline`, { method: 'POST', json: body })
