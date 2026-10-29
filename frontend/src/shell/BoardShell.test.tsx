import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Item } from '../api'
import { selection } from '../canvas/selection'
import { makeItem } from '../test/fixtures'
import { BoardShell } from './BoardShell'
import { closeRail, noteLensProposal, openRail, setTool, toolStore } from './tools'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ demo_mode: false }), { status: 200 }))
})

afterEach(() => {
  cleanup()
  selection.reset()
  setTool('select')
  closeRail()
})

const items: Item[] = [
  makeItem({ id: 'i1', original_filename: 'field-watch.jpg' }),
  makeItem({ id: 'i2', original_filename: 'dial-macro.png' }),
  makeItem({ id: 'i3', original_filename: 'staged-take.png', staged: true }),
]

function setup(over: { plugins?: boolean; explore?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onFocusItem = vi.fn()
  const onFindExamples = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <BoardShell
        boardId="b1"
        items={items}
        header={<span>HEADER</span>}
        canvas={<textarea aria-label="Note text" />}
        library={
          <>
            <p>LIBRARY EXTRAS</p>
            <label>
              Link to a page or image
              <input type="url" />
            </label>
          </>
        }
        onFocusItem={onFocusItem}
        onFindExamples={onFindExamples}
        plugins={over.plugins ?? true}
        explore={over.explore ?? true}
      />
    </QueryClientProvider>,
  )
  return { onFocusItem, onFindExamples }
}

const rail = () => within(screen.getByRole('navigation', { name: 'Panels' }))

describe('BoardShell', () => {
  it('renders the rail with Library, Search, Plugins, Vocabulary', () => {
    setup()
    expect(rail().getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      'Library',
      'Search',
      'Plugins',
      'Vocabulary',
    ])
  })

  it('has no Plugins icon and no Nodes tool when plugins are off', () => {
    setup({ plugins: false })
    expect(rail().getAllByRole('button')).toHaveLength(3)
    expect(rail().queryByRole('button', { name: 'Plugins' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Nodes' })).toBeNull()
  })

  it('hides the Axis tool when explore is off', () => {
    setup({ explore: false })
    expect(screen.queryByRole('button', { name: 'Axis' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Note' })).toBeTruthy()
  })

  it('opening Library shows the items list; picking one focuses it', () => {
    const { onFocusItem } = setup()
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    expect(rail().getByRole('button', { name: 'Library' }).getAttribute('aria-pressed')).toBe('true')
    const panel = screen.getByRole('dialog', { name: 'Library' })
    const list = within(panel).getByRole('list', { name: 'Items on this board' })
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual(['field-watch.jpg', 'dial-macro.png'])
    expect(within(panel).getByText('LIBRARY EXTRAS')).toBeTruthy()
    fireEvent.click(within(list).getByRole('button', { name: 'field-watch.jpg' }))
    expect(onFocusItem).toHaveBeenCalledWith(items[0])
  })

  it('clicking the open rail icon again closes its panel', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    expect(screen.queryByRole('dialog', { name: 'Library' })).toBeNull()
  })

  it('Esc closes the panel', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Vocabulary' }))
    const panel = screen.getByRole('dialog', { name: 'Vocabulary' })
    expect(panel.textContent).toContain('Vocabulary is coming soon.')
    fireEvent.keyDown(panel, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Vocabulary' })).toBeNull()
  })

  it('Search lists images and opens Find real examples for the chosen one', () => {
    const { onFindExamples } = setup()
    fireEvent.click(rail().getByRole('button', { name: 'Search' }))
    const panel = screen.getByRole('dialog', { name: 'Search' })
    fireEvent.click(within(panel).getByRole('button', { name: 'dial-macro.png' }))
    expect(onFindExamples).toHaveBeenCalledWith(items[1])
  })

  it('Plugins opens the plugins panel slot', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Plugins' }))
    expect(screen.getByRole('dialog', { name: 'Plugins' })).toBeTruthy()
  })

  it('n switches to the note tool, Escape back to select', () => {
    setup()
    fireEvent.keyDown(document.body, { key: 'n' })
    expect(toolStore.get()).toBe('note')
    expect(screen.getByRole('button', { name: 'Note' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(toolStore.get()).toBe('select')
    fireEvent.keyDown(document.body, { key: 'a' })
    expect(toolStore.get()).toBe('axis')
  })

  it('n while typing in a textarea does not change the tool', () => {
    setup()
    const ta = screen.getByLabelText('Note text')
    ta.focus()
    fireEvent.keyDown(ta, { key: 'n' })
    expect(toolStore.get()).toBe('select')
  })

  it('toolbar buttons pick the tool; Nodes opens the nodes menu', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Note' }))
    expect(toolStore.get()).toBe('note')
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    expect(screen.getByRole('button', { name: 'Select' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Nodes' }))
    expect(screen.getByRole('dialog', { name: 'Nodes' })).toBeTruthy()
  })

  it('opening the Inspect drawer hides the agent card', () => {
    setup()
    expect(screen.getByRole('complementary', { name: 'Muse agent' })).toBeTruthy()
    act(() => selection.openDrawer('inspect', 'i1'))
    expect(screen.queryByRole('complementary', { name: 'Muse agent' })).toBeNull()
  })

  it('picking an item in Library hands focus back to the board', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Library' })).getByRole('button', { name: 'dial-macro.png' }))
    expect(document.activeElement).toBe(screen.getByRole('region', { name: 'Canvas' }))
  })

  it('Escape in a text field of the panel keeps the panel and the typed text', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    const input = screen.getByLabelText('Link to a page or image') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'https://e.test/p' } })
    input.focus()
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.getByRole('dialog', { name: 'Library' })).toBeTruthy()
    expect((screen.getByLabelText('Link to a page or image') as HTMLInputElement).value).toBe('https://e.test/p')
  })

  it('Escape elsewhere in the panel closes it and resets the tool to select', () => {
    setup()
    setTool('note')
    fireEvent.click(rail().getByRole('button', { name: 'Library' }))
    fireEvent.keyDown(screen.getByRole('button', { name: 'Close Library' }), { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Library' })).toBeNull()
    expect(toolStore.get()).toBe('select')
  })

  it('opened from the rail, the panel takes focus; opened by the board, it does not', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Search' }))
    expect(document.activeElement).toBe(screen.getByRole('dialog', { name: 'Search' }))
    act(() => closeRail())
    const ta = screen.getByLabelText('Note text')
    ta.focus()
    act(() => openRail('library', 'auto'))
    expect(screen.getByRole('dialog', { name: 'Library' })).toBeTruthy()
    expect(document.activeElement).toBe(ta)
  })

  it('a lens proposal while another panel is open puts a dot on Library', () => {
    setup()
    fireEvent.click(rail().getByRole('button', { name: 'Search' }))
    act(() => noteLensProposal(true))
    const lib = rail().getByRole('button', { name: 'Library, new lens to review' })
    expect(lib.querySelector('.rail-dot')).toBeTruthy()
    fireEvent.click(lib)
    expect(rail().getByRole('button', { name: 'Library' }).querySelector('.rail-dot')).toBeNull()
  })
})
