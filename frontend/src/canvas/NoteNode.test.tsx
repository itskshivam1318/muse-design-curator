import { act, cleanup, render } from '@testing-library/react'
import type Konva from 'konva'
import { createRef } from 'react'
import { Layer, Stage } from 'react-konva'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { noteVisualizeStore } from '../events'
import { stubCanvasContext } from '../test/canvasStub'
import { makeItem } from '../test/fixtures'
import { NoteVisualizing } from './ItemNode'
import { NoteNode } from './NoteNode'
import { NOTE_MIN_H, NOTE_W } from './noteSize'
import type { CanvasPalette } from './palette'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  noteVisualizeStore.set({ ids: new Set() })
})

const palette: CanvasPalette = {
  accent: '#00f', ink: '#000', paper: '#eee', panel: '#fff', muted: '#666', rule: '#ccc',
  ok: '#0a0', warn: '#a60', bad: '#a00', note: '#ffe', noteEdge: '#bba',
}

const note = (text: string) =>
  makeItem({ id: 'n1', kind: 'note', origin: 'note', note_text: text, x: 10, y: 20, w: 220, h: 96 })

function draw(children: React.ReactNode) {
  stubCanvasContext()
  const stage = createRef<Konva.Stage>()
  render(
    <Stage ref={stage} width={800} height={600}>
      <Layer>{children}</Layer>
    </Stage>,
  )
  return stage
}

describe('NoteNode', () => {
  it('is a warm card: #fff6d9, radius 4, shadow, 14 px #3a3220 IBM Plex Sans text, 220 wide, at least 96 tall', () => {
    const stage = draw(<NoteNode item={note('Dark olive')} />)
    const group = stage.current!.findOne<Konva.Group>('#n1')!
    expect({ x: group.x(), y: group.y() }).toEqual({ x: 10, y: 20 })
    const card = group.findOne<Konva.Rect>('.note-card')!
    expect(card.fill()).toBe('#fff6d9')
    expect(card.cornerRadius()).toBe(4)
    expect(card.shadowEnabled()).toBe(true)
    expect(card.width()).toBe(NOTE_W)
    expect(card.height()).toBe(NOTE_MIN_H)
    const text = group.findOne<Konva.Text>('.note-text')!
    expect(text.text()).toBe('Dark olive')
    expect(text.fill()).toBe('#3a3220')
    expect(text.fontSize()).toBe(14)
    expect(text.fontFamily()).toContain('IBM Plex Sans')
  })

  it('grows with its text', () => {
    const long = Array.from({ length: 12 }, (_, i) => `line ${i}`).join('\n')
    const stage = draw(<NoteNode item={note(long)} />)
    expect(stage.current!.findOne<Konva.Rect>('.note-card')!.height()).toBeGreaterThan(NOTE_MIN_H)
  })
})

describe('NoteVisualizing', () => {
  it('draws a 190×150 placeholder beside the note with a dashed line only while visualizing', () => {
    const n = note('Strap')
    const stage = draw(<NoteVisualizing note={n} siblings={[]} scale={1} palette={palette} reduced />)
    expect(stage.current!.findOne('.note-placeholder')).toBeUndefined()
    act(() => noteVisualizeStore.set({ ids: new Set(['n1']) }))
    const card = stage.current!.findOne<Konva.Group>('.note-placeholder')!
    expect({ x: card.x(), y: card.y() }).toEqual({ x: 10 + 220 + 40, y: 20 })
    const frame = card.findOne<Konva.Rect>('.note-placeholder-card')!
    expect({ w: frame.width(), h: frame.height() }).toEqual({ w: 190, h: 150 })
    expect(card.findOne('.note-placeholder-progress')).toBeTruthy()
    expect(stage.current!.findOne<Konva.Line>('.note-placeholder-line')!.dash().length).toBeGreaterThan(0)
  })

  it('sits below images already made from the note, as the server places the next one', () => {
    const n = note('Strap')
    const earlier = makeItem({ id: 'g1', origin: 'generated', parent_item_id: 'n1', h: 150 })
    noteVisualizeStore.set({ ids: new Set(['n1']) })
    const stage = draw(<NoteVisualizing note={n} siblings={[earlier]} scale={1} palette={palette} reduced />)
    expect(stage.current!.findOne<Konva.Group>('.note-placeholder')!.y()).toBe(20 + 150 + 24)
  })
})
