import { loadSettings, saveSettings, listBoards, pairWithCode, type BoardSummary, type Settings } from './pair'

export interface Status { kind: 'ok' | 'error' | 'info'; text: string; boardId?: string }
export interface View { boards: BoardSummary[]; status: Status | null }
export interface Actions {
  pair(code: string): void
  addPage(boardId: string): void
  selectBoard(boardId: string): void
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, props: Partial<HTMLElementTagNameMap[K]> = {}, ...kids: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const node = Object.assign(document.createElement(tag), props)
  node.append(...kids)
  return node
}

export function renderPopup(root: HTMLElement, settings: Settings, view: View, actions: Actions): void {
  root.replaceChildren()
  const status = view.status
    ? el('p', { className: `status ${view.status.kind}`, role: 'status' }, view.status.text)
    : null

  if (!settings.token) {
    const input = el('input', {
      id: 'code', inputMode: 'numeric', maxLength: 6, autocomplete: 'off', placeholder: '000000',
    })
    const form = el('form', {},
      el('h1', {}, 'Pair with your board'),
      el('p', {}, 'Enter the 6-digit code shown in the app'),
      input,
      el('button', { type: 'submit', id: 'pair' }, 'Pair'),
      el('p', { id: 'api-note', className: 'note' },
        `App address: ${settings.apiBase}. This build talks to http://localhost:8000. ` +
        'To use another address, edit manifest.json host_permissions.'),
    )
    form.addEventListener('submit', (e) => { e.preventDefault(); actions.pair(input.value) })
    root.append(form)
    if (status) root.append(status)
    return
  }

  const select = el('select', { id: 'board' })
  for (const b of view.boards) {
    select.append(el('option', { value: b.id, selected: b.id === settings.lastBoardId }, b.title))
  }
  select.addEventListener('change', () => actions.selectBoard(select.value))
  const add = el('button', { id: 'add-page', type: 'button', disabled: view.boards.length === 0 }, 'Add this page')
  add.addEventListener('click', () => actions.addPage(select.value))
  root.append(
    view.boards.length ? select : el('p', {}, 'Create a board in the app first.'),
    add,
  )
  if (status) {
    root.append(status)
    if (view.status?.boardId) {
      const href = `${settings.appUrl}/boards/${view.status.boardId}`
      root.append(el('a', { href, target: '_blank', id: 'open-board' }, 'Open board'))
    }
  }
}

async function boot(): Promise<void> {
  const root = document.getElementById('app')
  if (!root) return
  let settings = await loadSettings()
  const view: View = { boards: [], status: null }
  const draw = () => renderPopup(root, settings, view, actions)

  const refresh = async () => {
    settings = await loadSettings()
    if (settings.token) {
      try {
        view.boards = await listBoards(settings)
        if (!view.boards.some((b) => b.id === settings.lastBoardId) && view.boards[0]) {
          settings.lastBoardId = view.boards[0].id
        }
      } catch (e) {
        view.status = { kind: 'error', text: (e as Error).message }
      }
    }
    draw()
  }

  const actions: Actions = {
    async pair(code) {
      try {
        await pairWithCode(settings, code)
        view.status = null
        await refresh()
      } catch (e) {
        view.status = { kind: 'error', text: (e as Error).message }
        draw()
      }
    },
    async selectBoard(id) {
      settings.lastBoardId = id
      await saveSettings({ lastBoardId: id })
    },
    async addPage(boardId) {
      await saveSettings({ lastBoardId: boardId })
      view.status = { kind: 'info', text: 'Adding…' }
      draw()
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
      const reply = (await chrome.runtime.sendMessage({ type: 'add-page', tabId: tab?.id, boardId })) as
        { ok: true; notice?: string } | { ok: false; error: string }
      if (reply.ok) {
        const title = view.boards.find((b) => b.id === boardId)?.title ?? 'board'
        view.status = { kind: 'ok', text: [`Added to ${title}`, reply.notice].filter(Boolean).join('. '), boardId }
      } else {
        view.status = { kind: 'error', text: reply.error }
      }
      await refresh()
    },
  }
  await refresh()
}

if (typeof chrome !== 'undefined' && chrome.storage?.local) void boot()
