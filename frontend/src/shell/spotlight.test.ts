import { afterEach, describe, expect, it } from 'vitest'
import { makeStep } from '../test/fixtures'
import {
  backSpot,
  closeSpotlight,
  currentStep,
  nextSpot,
  replaySteps,
  spotlightStore,
  startSpotlight,
} from './spotlight'

afterEach(() => closeSpotlight())

describe('spotlight replay', () => {
  it('leaves out refused and unstarred steps, in turn order', () => {
    const steps = [
      makeStep({ id: 's3', turn: 3, highlight: true, ok: true }),
      makeStep({ id: 's1', turn: 1, highlight: true, ok: false }),
      makeStep({ id: 's2', turn: 2, highlight: false, ok: true }),
      makeStep({ id: 's0', turn: 0, highlight: true, ok: true }),
    ]
    expect(replaySteps(steps).map((s) => s.id)).toEqual(['s0', 's3'])
  })

  it('steps forward and back, and closes past the last step', () => {
    startSpotlight('r1', [
      makeStep({ id: 'a', turn: 1, highlight: true }),
      makeStep({ id: 'b', turn: 2, highlight: true }),
    ])
    expect(currentStep(spotlightStore.get())?.id).toBe('a')
    backSpot()
    expect(spotlightStore.get()?.index).toBe(0)
    nextSpot()
    expect(currentStep(spotlightStore.get())?.id).toBe('b')
    nextSpot()
    expect(spotlightStore.get()).toBeNull()
  })

  it('does not start with nothing to play', () => {
    startSpotlight('r1', [makeStep({ highlight: false })])
    expect(spotlightStore.get()).toBeNull()
  })
})
