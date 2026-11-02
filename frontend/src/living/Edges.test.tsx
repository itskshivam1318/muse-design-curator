import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { AnalysisView } from '../api'
import { analysis, exp, item, opt } from '../test/explore'
import { makeItem } from '../test/fixtures'
import { Edges } from './Edges'
import { buildScene, type Scene } from './scene'
import { LivingProvider } from './useLiving'
import { createLivingWorld } from './world'

const view = { x: 0, y: 0, scale: 2 }

function setup(scene: Scene) {
  let t = 0
  let cb: FrameRequestCallback | null = null
  const world = createLivingWorld({ reduced: true, now: () => t, schedule: (f) => ((cb = f), 1), cancel: () => {} })
  world.sync(scene, -1000)
  render(
    <LivingProvider world={world}>
      <Edges scene={scene} view={view} />
    </LivingProvider>,
  )
  world.start()
  const frame = () => {
    t += 1000 / 60
    act(() => cb?.(t))
  }
  return { world, frame }
}

const path = (id: string) => document.querySelector<SVGPathElement>(`path[data-edge-id="${id}"]`)!

afterEach(cleanup)

describe('Edges', () => {
  const kept = makeItem({ id: 'k1', board_id: 'b1', x: 600, y: 0, w: 168, h: 105 })
  const scene = buildScene({
    items: [item, kept],
    explorations: [
      exp('e1', 'hand_style', [opt('o1'), opt('o2', { status: 'kept', kept_item_id: 'k1' })]),
      exp('e2', 'mood', [opt('o3', { exploration_id: 'e2' })]),
    ],
    analyses: new Map<string, AnalysisView | null>([['a', analysis]]),
    labels: new Map(),
    collapsed: () => false,
    selectedId: null,
  })

  it('draws one path per stem and spoke, tagged with its kind and id', () => {
    setup(scene)
    expect(document.querySelectorAll('path[data-edge-kind="stem"]')).toHaveLength(2)
    expect(document.querySelectorAll('path[data-edge-kind="spoke"]')).toHaveLength(3)
    expect(path('stem:e1')).toBeTruthy()
    expect(path('spoke:o1')).toBeTruthy()
  })

  it('a stem is a cubic from its anchor on the item, a spoke a quadratic; written at once and every frame', () => {
    const { frame } = setup(scene)
    // the hands part sits at (170, 75) on item a
    expect(path('stem:e1').getAttribute('d')).toMatch(/^M170,75 C/)
    expect(path('spoke:o1').getAttribute('d')).toMatch(/^M[-\d.]+,[-\d.]+ Q/)
    const before = path('spoke:o1').getAttribute('d')
    for (let i = 0; i < 20; i++) frame()
    expect(path('spoke:o1').getAttribute('d')).not.toBe(before) // the petal grew out from its hub
  })

  it("a kept take's spoke is marked kept; the others are not", () => {
    setup(scene)
    expect(path('spoke:o2').classList.contains('is-kept')).toBe(true)
    expect(path('spoke:o1').classList.contains('is-kept')).toBe(false)
  })

  it("an anchor dot sits at each stem's source, sized for the zoom", () => {
    setup(scene)
    const dots = [...document.querySelectorAll<SVGCircleElement>('circle.flower-root')]
    expect(dots).toHaveLength(2)
    expect(dots.map((d) => [d.getAttribute('cx'), d.getAttribute('cy')])).toContainEqual(['170', '75'])
    expect(dots[0].getAttribute('r')).toBe('2.25')
  })

  it('draws no leader paths: the callouts draw their own', () => {
    const selected = buildScene({
      items: [item],
      explorations: [exp('e1', 'hand_style', [opt('o1')])],
      analyses: new Map<string, AnalysisView | null>([['a', analysis]]),
      labels: new Map(),
      collapsed: () => false,
      selectedId: 'a',
    })
    setup(selected)
    expect(document.querySelectorAll('path[data-edge-kind="leader"]')).toHaveLength(0)
    expect(document.querySelectorAll('path[data-edge-kind="stem"]')).toHaveLength(1)
  })
})
