import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Layer, Stage } from 'react-konva'
import { makeItem } from '../test/fixtures'
import { stubCanvasContext } from '../test/canvasStub'
import type Konva from 'konva'
import { createRef } from 'react'
import type { VerdictTone } from '../explore/verdict'
import { ItemDecorations, ItemNode } from './ItemNode'
import type { CanvasPalette } from './palette'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const palette: CanvasPalette = {
  accent: '#00f', ink: '#000', paper: '#eee', panel: '#fff', muted: '#666', rule: '#ccc',
  ok: '#0a0', warn: '#a60', bad: '#a00', note: '#ffe', noteEdge: '#bba',
}
const handlers = {
  onPointerDown: vi.fn(), onDragStart: vi.fn(), onDragMove: vi.fn(), onDragEnd: vi.fn(),
  onEnter: vi.fn(), onLeave: vi.fn(),
}

describe('link card', () => {
  it('makes no request outside /api when rendering a link card', () => {
    stubCanvasContext()
    const srcs: string[] = []
    const desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src')!
    vi.spyOn(HTMLImageElement.prototype, 'src', 'set').mockImplementation(function (this: HTMLImageElement, v: string) {
      srcs.push(v)
      desc.set!.call(this, v)
    })
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const link = makeItem({
      id: 'lnk', kind: 'link', page_url: 'https://www.instagram.com/p/abc/', source_url: null,
      page_title: 'Instagram', storage_path: null, thumb_path: null, parse_status: 'failed',
      parse_error_code: 'LINK_NEEDS_EXTENSION', w: 240, h: 160,
    })
    render(
      <Stage width={400} height={300}>
        <Layer>
          <ItemNode item={link} scale={1} draggable palette={palette} handlers={handlers} />
        </Layer>
      </Stage>,
    )
    expect(srcs.filter((s) => !s.startsWith('/api/'))).toEqual([])
    expect(srcs).toEqual([]) // a link card loads no images at all
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('generated badge', () => {
  const gen = { model: 'm', prompt: 'p', option_id: 'o1' }
  function badge(item = makeItem({ origin: 'generated', generation: gen }), tone?: VerdictTone) {
    stubCanvasContext()
    const stage = createRef<Konva.Stage>()
    render(
      <Stage ref={stage} width={400} height={300}>
        <Layer>
          <ItemDecorations
            item={item}
            bounds={{ x: 10, y: 20, width: 200, height: 150 }}
            scale={1}
            hovered={false}
            selected={false}
            reduced
            palette={palette}
            verdictTone={tone}
          />
        </Layer>
      </Stage>,
    )
    const label = stage.current!.findOne<Konva.Label>('.generated-badge')
    const out = label && { text: label.getText().text(), fill: label.getTag().fill() }
    cleanup()
    return out
  }

  it('is always on a generated item, tinted by its check', () => {
    expect(badge()).toEqual({ text: 'generated', fill: palette.muted })
    expect(badge(undefined, 'pending')).toEqual({ text: 'generated', fill: palette.muted })
    expect(badge(undefined, 'ok')?.fill).toBe(palette.ok)
    expect(badge(undefined, 'warn')?.fill).toBe(palette.warn)
    expect(badge(undefined, 'error')?.fill).toBe(palette.bad)
  })

  it('is not on other items', () => {
    expect(badge(makeItem())).toBeUndefined()
  })
})
