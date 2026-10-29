import { act, cleanup, render } from '@testing-library/react'
import type Konva from 'konva'
import { createRef } from 'react'
import { Layer, Stage } from 'react-konva'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExploreOption } from '../api'
import { hoverStore, setHoveredOption } from '../explore/hover'
import { stubCanvasContext } from '../test/canvasStub'
import { OptionNote } from './OptionNote'
import type { CanvasPalette } from './palette'

afterEach(() => {
  cleanup()
  setHoveredOption(null)
})

const palette: CanvasPalette = {
  accent: '#00f', ink: '#000', paper: '#eee', panel: '#fff', muted: '#666', rule: '#ccc',
  ok: '#0a0', warn: '#a60', bad: '#a00', note: '#ffe', noteEdge: '#bba',
}

const option: ExploreOption = {
  id: 'o1', exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: 'Brushed steel',
  description: 'A satin grain that softens reflections.', distance: 'bold', value: 'brushed', keeps: [],
  status: 'open', last_error: null, kept_item_id: null, takes: [], x: 300, y: 40,
}

function setup(over: { editable?: boolean; option?: Partial<ExploreOption> } = {}) {
  stubCanvasContext()
  const stage = createRef<Konva.Stage>()
  const props = { onOpen: vi.fn(), onMove: vi.fn(), onDragMove: vi.fn(), onDismiss: vi.fn() }
  render(
    <Stage ref={stage} width={800} height={600}>
      <Layer>
        <OptionNote option={{ ...option, ...over.option }} x={300} y={40} scale={1} palette={palette} editable={over.editable ?? true} {...props} />
      </Layer>
    </Stage>,
  )
  const find = <T extends Konva.Node>(name: string) => stage.current!.findOne<T>(`.${name}`)
  return { ...props, find }
}

describe('OptionNote', () => {
  it('shows a one-line state while visualizing and after a failure', () => {
    expect(setup().find<Konva.Text>('note-state')).toBeUndefined()
    cleanup()
    const busy = setup({ option: { status: 'visualizing' } }).find<Konva.Text>('note-state')!
    expect(busy.text()).toBe('visualizing…')
    expect(busy.fill()).toBe(palette.muted)
    cleanup()
    const failed = setup({ option: { last_error: 'MODEL_UNAVAILABLE' } }).find<Konva.Text>('note-state')!
    expect(failed.text()).toBe("couldn't visualize")
    expect(failed.fill()).toBe(palette.bad)
  })

  it('OptionNote renders name and distance', () => {
    const { find } = setup()
    expect(find<Konva.Text>('note-name')?.text()).toBe('Brushed steel')
    expect(find<Konva.Text>('note-distance')?.text()).toBe('bold')
    const desc = find<Konva.Text>('note-desc')!
    expect(desc.text()).toBe(option.description)
    expect(desc.ellipsis()).toBe(true)
    expect(desc.height()).toBeCloseTo(2 * desc.fontSize() * desc.lineHeight())
  })

  it('drag end patches position', () => {
    const { find, onMove } = setup()
    const note = find<Konva.Group>('option-note')!
    expect(note.draggable()).toBe(true)
    note.position({ x: 412.6, y: 90.2 })
    act(() => {
      note.fire('dragend', { evt: new MouseEvent('mouseup') })
    })
    expect(onMove).toHaveBeenCalledWith(option, { x: 300, y: 40 }, { x: 413, y: 90 })
  })

  it('hovered note outlined', () => {
    const { find } = setup()
    const card = find<Konva.Rect>('note-card')!
    expect(card.stroke()).toBe(palette.noteEdge)
    act(() => setHoveredOption('o1'))
    expect(card.stroke()).toBe(palette.accent)
    act(() => setHoveredOption('other'))
    expect(card.stroke()).toBe(palette.noteEdge)
  })

  it('hovering the note sets the hovered option; clicking opens it', () => {
    const { find, onOpen } = setup()
    const note = find<Konva.Group>('option-note')!
    act(() => {
      note.fire('mouseenter', { evt: new MouseEvent('mouseover') })
    })
    expect(hoverStore.get()).toBe('o1')
    act(() => {
      note.fire('mouseleave', { evt: new MouseEvent('mouseout') })
    })
    expect(hoverStore.get()).toBeNull()
    act(() => {
      note.fire('click', { evt: new MouseEvent('click') })
    })
    expect(onOpen).toHaveBeenCalledWith(option)
  })

  it('× dismisses without opening', () => {
    const { find, onOpen, onDismiss } = setup()
    act(() => {
      find<Konva.Group>('note-dismiss')!.fire('click', { evt: new MouseEvent('click') }, true)
    })
    expect(onDismiss).toHaveBeenCalledWith(option)
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('locked: not draggable and no ×', () => {
    const { find } = setup({ editable: false })
    expect(find<Konva.Group>('option-note')!.draggable()).toBe(false)
    expect(find('note-dismiss')).toBeUndefined()
  })
})
