import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import { apiOrigin } from './api'

describe('apiOrigin', () => {
  it('is empty (same origin, dev proxy) when VITE_API_URL is unset or blank', () => {
    expect(apiOrigin(undefined)).toBe('')
    expect(apiOrigin('  ')).toBe('')
  })

  it('drops trailing slashes so paths join cleanly', () => {
    expect(apiOrigin('https://user-dle.hf.space/')).toBe('https://user-dle.hf.space')
    expect(apiOrigin('https://api.example.com//')).toBe('https://api.example.com')
  })
})

describe('round 2 calls', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  const last = () => {
    const [url, init] = fetchMock.mock.calls.at(-1)!
    return {
      path: String(url).replace(/^.*\/api/, ''),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(init.body) : undefined,
    }
  }

  it.each([
    ['createNote', () => api.createNote('b 1', { text: 'hi', x: 1, y: 2 }), '/boards/b%201/notes', 'POST', { text: 'hi', x: 1, y: 2 }],
    ['patchNoteText', () => api.patchNoteText('i1', 'new'), '/items/i1', 'PATCH', { note_text: 'new' }],
    ['visualizeNote', () => api.visualizeNote('i1'), '/items/i1/visualize', 'POST', undefined],
    ['keepTake', () => api.keepTake('o1', 'i1', { x: 3, y: 4 }), '/options/o1/keep', 'POST', { item_id: 'i1', x: 3, y: 4 }],
    ['keepTake no position', () => api.keepTake('o1', 'i1'), '/options/o1/keep', 'POST', { item_id: 'i1' }],
    ['unkeepTake', () => api.unkeepTake('o1'), '/options/o1/unkeep', 'POST', undefined],
    ['listPlugins', () => api.listPlugins(), '/plugins', 'GET', undefined],
    ['listPacks', () => api.listPacks(), '/plugin-packs', 'GET', undefined],
    ['listBoardPlugins', () => api.listBoardPlugins('b'), '/boards/b/plugins', 'GET', undefined],
    ['addBoardPlugin', () => api.addBoardPlugin('b', 'palette'), '/boards/b/plugins', 'POST', { plugin_id: 'palette' }],
    ['removeBoardPlugin', () => api.removeBoardPlugin('b', 'palette'), '/boards/b/plugins/palette', 'DELETE', undefined],
    ['listNodes', () => api.listNodes('b'), '/boards/b/nodes', 'GET', undefined],
    ['createNode', () => api.createNode('b', { plugin_id: 'palette', x: 1, y: 2, input_item_ids: ['i1'] }), '/boards/b/nodes', 'POST', { plugin_id: 'palette', x: 1, y: 2, input_item_ids: ['i1'] }],
    ['patchNode', () => api.patchNode('n1', { x: 5 }), '/nodes/n1', 'PATCH', { x: 5 }],
    ['deleteNode', () => api.deleteNode('n1'), '/nodes/n1', 'DELETE', undefined],
    ['runNode', () => api.runNode('n1'), '/nodes/n1/run', 'POST', undefined],
  ] as const)('%s sends the right request', async (_name, call, path, method, body) => {
    await call()
    expect(last()).toEqual({ path, method, body })
  })

  it('has keys for the plugin queries', () => {
    expect(api.keys.plugins()).toEqual(['plugins'])
    expect(api.keys.packs()).toEqual(['plugin-packs'])
    expect(api.keys.boardPlugins('b')).toEqual(['boardPlugins', 'b'])
    expect(api.keys.nodes('b')).toEqual(['nodes', 'b'])
  })
})

describe('analysis calls', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
  const lastCall = () => {
    const [url, init] = fetchMock.mock.calls.at(-1)!
    return {
      path: String(url).replace(/^.*\/api/, ''),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(init.body) : undefined,
    }
  }

  it('getAnalysis reads the item analysis', async () => {
    const view = { content_type: 'ui', parse_status: 'completed', parts: [], dimensions: [] }
    fetchMock.mockResolvedValue(json(view))
    expect(await api.getAnalysis('i 1')).toEqual(view)
    expect(lastCall()).toEqual({ path: '/items/i%201/analysis', method: 'GET', body: undefined })
  })

  it('extractPart posts to the part extract path', async () => {
    fetchMock.mockResolvedValue(json({ id: 'new' }))
    await api.extractPart('i1', 'hero')
    expect(lastCall()).toEqual({ path: '/items/i1/parts/hero/extract', method: 'POST', body: undefined })
  })

  it('visualizeOption sends renderer_id, and nothing when given nothing', async () => {
    fetchMock.mockImplementation(async () => json({}))
    await api.visualizeOption('o1', { renderer_id: 'r1', at: { x: 1, y: 2 } })
    expect(lastCall()).toEqual({ path: '/options/o1/visualize', method: 'POST', body: { x: 1, y: 2, renderer_id: 'r1' } })
    await api.visualizeOption('o1')
    expect(lastCall().body).toBeUndefined()
  })

  it('acceptOffer posts the offer identity', async () => {
    fetchMock.mockResolvedValue(json({ your_words: '', learned: [], offers: [] }))
    await api.acceptOffer('b1', { label: 'Mood', dim_type: 'abstract', kind: 'enum', part: null })
    expect(lastCall()).toEqual({
      path: '/boards/b1/offers/accept',
      method: 'POST',
      body: { label: 'Mood', dim_type: 'abstract', kind: 'enum', part: null },
    })
  })

  it('a 429 surfaces the server message', async () => {
    const message = 'Daily limit reached for this board, try tomorrow.'
    fetchMock.mockResolvedValue(json({ error: { code: 'RATE_LIMITED', message } }, 429))
    await expect(api.analyseItem('i1')).rejects.toMatchObject({ status: 429, code: 'RATE_LIMITED', message })
  })
})
