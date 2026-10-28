/**
 * Typed client for the FastAPI backend (everything under /api). In dev Vite proxies /api; a deployed
 * frontend whose API lives on another origin sets VITE_API_URL (e.g. https://user-dle.hf.space).
 */

export type ParseStatus = 'pending' | 'pending_lens' | 'processing' | 'completed' | 'failed'
export type ItemKind = 'image' | 'video' | 'link'
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
  created_at: string
  /** Stored provenance of a licensed (corpus) image; null for the user's own items. */
  licence?: ItemLicence | null
  /** Set on an image generated from an explore option. */
  explore_option_id: string | null
  generation: { model: string; prompt: string; option_id: string } | null
  check: GeneratedCheck | null
}

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
  status: 'open' | 'dismissed' | 'visualizing' | 'visualized'
  last_error: string | null
  x: number | null
  y: number | null
  created_at?: string
}

export interface Exploration {
  id: string
  board_id: string
  item_id: string
  key: string
  created_at?: string
  options: ExploreOption[]
}

export interface ItemLicence {
  credit: string
  license_code: string
  license_url: string | null
  creator_name: string | null
  landing_url: string | null
  source: string
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

export type VaryMode = 'explore' | 'prefer' | 'avoid' | 'nudge'

export interface VariationRequest {
  source_item_id: string
  target_key: string
  mode: VaryMode
  target_values: string[]
  protected_keys: string[]
  nudge: { direction: 'more' | 'less'; steps: 1 | 2 } | null
}

export type CandidateState = 'retrieved' | 'excluded' | 'validating' | 'validated' | 'uncertain' | 'rejected'
export type Verdict = 'pass' | 'fail' | 'uncertain'

export interface CandidateCheck {
  check: string
  attribute_key: string | null
  verdict: Verdict
  reason: string
  evidence: { source?: string; values?: Record<string, unknown> } | null
}

export interface DecisionRow {
  id: string
  decision: 'keep' | 'reject'
  reason_code: string | null
  note: string | null
  item_id: string | null
  created_at: string
}

export interface CandidateView {
  id: string
  corpus_item_id: string
  image_url: string
  width: number | null
  height: number | null
  provenance: { credit: string | null; landing_url: string | null; license_code: string | null; creator_name: string | null }
  /** Where this run found it: the pre-indexed library, or a live licensed-source search. */
  origin: 'corpus' | 'live'
  /** The source adapter id (e.g. 'commons'). */
  source?: string
  state: CandidateState
  rank: number | null
  scores: Record<string, number> | null
  checks: CandidateCheck[]
  observed_target_value: AttrValue
  decision: DecisionRow | null
  decisions: DecisionRow[]
}

export interface ShortfallLine {
  code: string
  count: number
  message: string
}

/** `skipped`: the source is cooling down after refusing us or timing out, so it was not asked. */
export type LiveSourceStatus = 'ok' | 'failed' | 'timeout' | 'skipped'

/** Live search progress: which sources answered, and how many candidates they found so far. */
export interface LiveProgress {
  sources: Record<string, LiveSourceStatus>
  /** The source ids being searched (before they report). */
  searching?: string[]
  downloaded?: number
  found: number
  queries?: string[]
}

export interface LiveSummary {
  queries: string[]
  found: number
  kept: number
  sources: Record<string, LiveSourceStatus>
  failed?: { source: string; error_code: string | null }[]
}

export interface RunSummary {
  pool_size: number
  excluded: Record<string, number>
  validated: number
  uncertain: number
  rejected: number
  returned: number
  shortfall?: ShortfallLine[]
  live?: LiveSummary
}

export type RunStatus = 'queued' | 'retrieving' | 'validating' | 'completed' | 'failed'

export interface RunInfo {
  id: string
  board_id: string
  source_item_id: string
  lens_id: string
  target_key: string
  mode: VaryMode
  target_values: string[]
  nudge: { direction: 'more' | 'less'; steps: 1 | 2 } | null
  protected_keys: string[]
  status: RunStatus
  error_code: string | null
  created_at: string
  completed_at: string | null
}

export interface RunResponse {
  run: RunInfo
  progress: { stage: string; validated_n?: number; shortlist_n?: number; live?: LiveProgress } | null
  summary: RunSummary | null
  results: CandidateView[]
  needs_review: CandidateView[]
  rejected: CandidateView[]
  excluded_counts: Record<string, number>
}

export interface DecisionBody {
  decision: 'keep' | 'reject'
  reason_code?: string
  note?: string
  mark_not_this?: boolean
}

export interface DecisionResponse {
  decision: DecisionRow
  history: DecisionRow[]
  item: Item | null
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
  attributeHistory: (itemId: string, key: string) => ['attributeHistory', itemId, key] as const,
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
  body: Partial<Pick<Item, 'x' | 'y' | 'w' | 'h' | 'z' | 'role'>> & { chosen_frame_id?: string },
) => request<Item>(`/items/${enc(id)}`, { method: 'PATCH', json: body })
export const deleteItem = (id: string) => request<void>(`/items/${enc(id)}`, { method: 'DELETE' })
export const listFrames = (itemId: string) =>
  request<{ frames: Frame[] }>(`/items/${enc(itemId)}/frames`).then((r) => r.frames)

/** The board's current lens, or its newest proposal; null when it has none yet. */
export const getBoardLens = (boardId: string) =>
  request<{ lens: LensRow | null }>(`/boards/${enc(boardId)}/lens`).then((r) => r.lens)
export const getLens = (lensId: string) => request<LensRow>(`/lenses/${enc(lensId)}`)
/** Confirm the proposal as-is (no body) or save an edited spec. */
export const confirmLens = (boardId: string, spec?: LensSpec) =>
  request<LensRow>(`/boards/${enc(boardId)}/lens`, {
    method: 'PUT',
    ...(spec ? { json: spec } : {}),
  })
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
  body: { status?: 'dismissed' | 'open'; x?: number; y?: number },
) => request<ExploreOption>(`/options/${enc(optionId)}`, { method: 'PATCH', json: body })
/** `at` is where the canvas draws the option's note; the server saves it and places the image beside it. */
export const visualizeOption = (optionId: string, at?: Point) =>
  request<void>(`/options/${enc(optionId)}/visualize`, { method: 'POST', ...(at ? { json: at } : {}) })

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

/** Start a variation run. One Idempotency-Key per Run click, so a retried request never runs twice. */
export const createRun = (boardId: string, body: VariationRequest, idempotencyKey: string) =>
  request<{ run_id: string }>(`/boards/${enc(boardId)}/runs`, {
    method: 'POST',
    json: body,
    headers: { 'Idempotency-Key': idempotencyKey },
  })
export const getRun = (runId: string) => request<RunResponse>(`/runs/${enc(runId)}`)
export const postDecision = (runId: string, candidateId: string, body: DecisionBody, idempotencyKey: string) =>
  request<DecisionResponse>(`/runs/${enc(runId)}/candidates/${enc(candidateId)}/decisions`, {
    method: 'POST',
    json: body,
    headers: { 'Idempotency-Key': idempotencyKey },
  })
export const corpusImageUrl = (corpusId: string) => `${BASE}/corpus/${enc(corpusId)}/image`

/** Short cache-busting token: the thumbnail path changes when a video's chosen frame changes. */
function version(item: Item): string {
  return (item.thumb_path ?? item.storage_path ?? '').replace(/[^a-z0-9]/gi, '').slice(-12)
}

export const itemImageUrl = (item: Item, size: 'thumb' | 'full') =>
  `${BASE}/items/${enc(item.id)}/image?size=${size}&v=${version(item)}`
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
