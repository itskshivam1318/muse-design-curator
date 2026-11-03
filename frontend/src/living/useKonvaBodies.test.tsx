import { act, cleanup, render } from '@testing-library/react'
import Konva from 'konva'
import { useRef } from 'react'
import { Group, Layer, Line, Rect, Stage } from 'react-konva'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { stubCanvasContext } from '../test/canvasStub'
import type { BodySpec } from './physics'
import type { Scene } from './scene'
import { useKonvaBodies } from './useKonvaBodies'
import { createLivingWorld, type LivingWorld } from './world'

const item = (id: string, x: number, y: number): BodySpec => ({ id, kind: 'item', w: 100, h: 80, home: { kind: 'abs', x, y } })
const scene = (...specs: BodySpec[]): Scene => ({ specs, edges: [], flowers: [], docked: new Map(), slots: new Map() })

function Board({ world }: { world: LivingWorld }) {
  const layer = useRef<Konva.Layer>(null)
  useKonvaBodies(world, layer)
  return (
    <Stage width={800} height={600}>
      <Layer ref={layer}>
        <Rect id="a" x={0} y={0} width={100} height={80} draggable />
        <Group name="deco" body="a" />
        <Rect id="b" x={0} y={0} width={100} height={80} />
        <Line name="living-link" link={['a', 'b']} points={[]} />
        <Rect id="c" x={0} y={0} width={200} height={160} natW={200} />
      </Layer>
    </Stage>
  )
}

function setup() {
  let t = 0
  let cb: FrameRequestCallback | null = null
  const world = createLivingWorld({ reduced: true, now: () => t, schedule: (f) => ((cb = f), 1), cancel: () => {} })
  world.sync(scene(item('a', 200, 100), item('b', 500, 100), item('c', 200, 400)), -1000)
  world.setPinned(['a', 'b', 'c'])
  render(<Board world={world} />)
  world.start()
  const frame = () => {
    t += 1000 / 60
    act(() => cb?.(t))
  }
  const layer = Konva.stages.at(-1)!.getLayers()[0]
  return { world, frame, node: (sel: string) => layer.findOne(sel)! }
}

beforeEach(stubCanvasContext)
afterEach(cleanup)

describe('useKonvaBodies', () => {
  it("puts each item node, and anything tagged with its body, at the body's top-left at its grow scale", () => {
    const { frame, node } = setup()
    frame()
    expect(node('#a').position()).toEqual({ x: 150, y: 60 })
    expect(node('#a').scale()).toEqual({ x: 1, y: 1 })
    expect(node('.deco').position()).toEqual({ x: 150, y: 60 })
    expect(node('#b').position()).toEqual({ x: 450, y: 60 })
  })

  it("a node laid out at another width (natW) is drawn at its body's size, easing with it", () => {
    const { frame, node } = setup()
    frame()
    // laid out 200 wide, its body 100: drawn at half, its top-left where the body's is
    expect(node('#c').scale()).toEqual({ x: 0.5, y: 0.5 })
    expect(node('#c').position()).toEqual({ x: 150, y: 360 })
  })

  it('redraws a link between two bodies from where they are', () => {
    const { frame, node } = setup()
    frame()
    // a's right edge to b's left edge, at their middles
    expect((node('.living-link') as Konva.Line).points()).toEqual([250, 100, 350, 100, 350, 100, 450, 100])
  })

  it('does not redraw the layer when nothing moved', () => {
    const { frame, node } = setup()
    frame()
    frame() // settled (both pinned)
    const layer = node('#a').getLayer()!
    let draws = 0
    const orig = layer.batchDraw.bind(layer)
    layer.batchDraw = () => {
      draws++
      return orig()
    }
    frame()
    expect(draws).toBe(0)
  })

  it('leaves the node Konva is dragging alone', () => {
    const { world, frame, node } = setup()
    frame()
    const a = node('#a')
    a.startDrag()
    a.position({ x: 400, y: 300 })
    world.place('a', { x: 0, y: 0 })
    frame()
    expect(a.position()).toEqual({ x: 400, y: 300 })
    a.stopDrag()
    frame()
    expect(a.position()).toEqual({ x: -50, y: -40 })
  })
})
