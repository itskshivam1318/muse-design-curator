// Settings, pairing and backend calls. Everything lives in chrome.storage.local.
import type { CapturePayload } from './capture'

export interface Settings {
  apiBase: string
  appUrl: string
  token: string | null
  lastBoardId: string | null
}

export const DEFAULTS: Settings = {
  apiBase: 'http://localhost:8000',
  appUrl: 'http://localhost:5173',
  token: null,
  lastBoardId: null,
}

export interface BoardSummary { id: string; title: string; updated_at: string }

export async function loadSettings(): Promise<Settings> {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS))
  return { ...DEFAULTS, ...stored }
}

export async function saveSettings(patch: Partial<Settings>): Promise<void> {
  await chrome.storage.local.set(patch)
}

export function pairRequestBody(code: string): { code: string } {
  return { code: code.trim() }
}

export class ApiError extends Error {
  constructor(message: string, readonly code: string) {
    super(message)
  }
}

export async function api(
  settings: Settings,
  path: string,
  init: RequestInit = {},
  fetchFn: typeof fetch = fetch,
): Promise<Response> {
  const headers = new Headers(init.headers)
  if (settings.token) headers.set('Authorization', `Bearer ${settings.token}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  try {
    return await fetchFn(`${settings.apiBase}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(`Couldn't reach the app at ${settings.apiBase}. Is it running?`, 'UNREACHABLE')
  }
}

async function errorOf(res: Response): Promise<ApiError> {
  try {
    const body = await res.json()
    return new ApiError(body.error?.message ?? 'Something went wrong', body.error?.code ?? 'ERROR')
  } catch {
    return new ApiError('Something went wrong', 'ERROR')
  }
}

export async function pairWithCode(settings: Settings, code: string): Promise<string> {
  const res = await api(settings, '/api/extension/pair', {
    method: 'POST',
    body: JSON.stringify(pairRequestBody(code)),
  })
  if (!res.ok) {
    const err = await errorOf(res)
    if (err.code === 'PAIR_CODE_INVALID') {
      throw new ApiError('That code did not work. Check the code shown in the app and try again.', err.code)
    }
    throw err
  }
  const { token } = (await res.json()) as { token: string }
  await saveSettings({ token })
  return token
}

export async function listBoards(settings: Settings): Promise<BoardSummary[]> {
  const res = await api(settings, '/api/boards')
  if (!res.ok) throw await errorOf(res)
  return ((await res.json()) as { boards: BoardSummary[] }).boards
}

export async function postCapture(
  settings: Settings,
  boardId: string,
  capture: CapturePayload,
): Promise<void> {
  const res = await api(settings, `/api/boards/${boardId}/items`, {
    method: 'POST',
    body: JSON.stringify({ capture }),
  })
  if (res.ok) return
  const err = await errorOf(res)
  if (err.code === 'EXTENSION_UNAUTHORIZED') {
    await saveSettings({ token: null })
    throw new ApiError('This extension is no longer paired. Open it and enter a new code.', err.code)
  }
  throw err
}
