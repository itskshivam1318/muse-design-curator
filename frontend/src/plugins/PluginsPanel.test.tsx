import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { keys, type PluginPack } from '../api'
import { makePlugin } from '../test/plugins'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  addBoardPlugin: vi.fn(),
  removeBoardPlugin: vi.fn(() => Promise.resolve()),
}))
const api = await import('../api')
const { PluginsPanel } = await import('./PluginsPanel')
const { LOCKED_TITLE } = await import('../demo')

const plugins = [
  makePlugin(),
  makePlugin({ id: 'palette', name: 'Palette & material', description: 'Swatches from a group.', mark: 'PAL', runs_on: 'SAM 3.1 + Lab' }),
  makePlugin({ id: 'video', name: 'Video', description: 'Short clips.', mark: 'VID', runs_on: '[video model]', status: 'not_connected' }),
]
const packs: PluginPack[] = [
  { id: 'product', name: 'Product design', about: 'Objects you hold.', plugin_ids: ['image', 'missing'] },
  { id: 'fashion', name: 'Fashion', about: 'Garments.', plugin_ids: ['image', 'video', 'palette'] },
]

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
  vi.mocked(api.addBoardPlugin).mockImplementation(async (_b, id) => [id])
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function setup(added: string[] = [], locked = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.demo, { demo_mode: locked, unlocked: false, plugins_enabled: true })
  qc.setQueryData(keys.plugins(), plugins)
  qc.setQueryData(keys.packs(), packs)
  qc.setQueryData(keys.boardPlugins('b1'), added)
  render(
    <QueryClientProvider client={qc}>
      <PluginsPanel boardId="b1" />
    </QueryClientProvider>,
  )
  return qc
}

const rows = () => within(screen.getByRole('list', { name: /plugins in/i })).getAllByRole('listitem')

describe('PluginsPanel', () => {
  it('lists the packs with counts and the first pack’s plugins', () => {
    setup()
    const product = screen.getByRole('button', { name: /Product design/ })
    expect(product.getAttribute('aria-pressed')).toBe('true')
    expect(product.textContent).toContain('1') // the unknown id is not counted
    expect(rows()).toHaveLength(1)
    expect(rows()[0].textContent).toContain('Image')
    expect(rows()[0].textContent).toContain('Muse Spark')
  })

  it('switching pack lists its plugins', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: /Fashion/ }))
    expect(screen.getByRole('button', { name: /Fashion/ }).getAttribute('aria-pressed')).toBe('true')
    expect(rows().map((r) => r.querySelector('.plugin-name')?.textContent)).toEqual(['Image', 'Video', 'Palette & material'])
    expect(screen.getByText('Garments.')).toBeTruthy()
  })

  it('Add calls addBoardPlugin, then shows Added', async () => {
    const qc = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Add Image' }))
    expect(api.addBoardPlugin).toHaveBeenCalledWith('b1', 'image')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Added Image' })).toBeTruthy())
    expect(qc.getQueryData(keys.boardPlugins('b1'))).toEqual(['image'])
  })

  it('Added removes the plugin from the board again', async () => {
    setup(['image'])
    fireEvent.click(screen.getByRole('button', { name: 'Added Image' }))
    expect(api.removeBoardPlugin).toHaveBeenCalledWith('b1', 'image')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add Image' })).toBeTruthy())
  })

  it('a not-connected plugin shows the tag and can still be added', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: /Fashion/ }))
    const video = rows()[1]
    expect(within(video).getByText('Not connected')).toBeTruthy()
    const add = within(video).getByRole('button', { name: 'Add Video' }) as HTMLButtonElement
    expect(add.disabled).toBe(false)
    fireEvent.click(add)
    expect(api.addBoardPlugin).toHaveBeenCalledWith('b1', 'video')
  })

  it('Add and Added are disabled on a locked demo', () => {
    setup(['image'], true)
    fireEvent.click(screen.getByRole('button', { name: /Fashion/ }))
    const added = screen.getByRole('button', { name: 'Added Image' }) as HTMLButtonElement
    const add = screen.getByRole('button', { name: 'Add Video' }) as HTMLButtonElement
    expect(added.disabled).toBe(true)
    expect(add.disabled).toBe(true)
    expect(add.title).toBe(LOCKED_TITLE)
  })

  it('search narrows the rows', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: /Fashion/ }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search plugins' }), { target: { value: 'swatch' } })
    expect(rows()).toHaveLength(1)
    expect(rows()[0].textContent).toContain('Palette')
  })

  it('names the docs for building a plugin', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Build a plugin' }))
    expect(screen.getByText('docs/plugins.md')).toBeTruthy()
  })
})
