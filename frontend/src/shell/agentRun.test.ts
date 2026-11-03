import { describe, expect, it } from 'vitest'
import { makeRun, makeStep } from '../test/fixtures'
import { deliverableStatus, mergeFetched, mergeSteps, toolCall } from './agentRun'

describe('mergeSteps', () => {
  it('appends a new step and keeps turn order', () => {
    const a = makeStep({ id: 'a', turn: 1 })
    const c = makeStep({ id: 'c', turn: 3 })
    const b = makeStep({ id: 'b', turn: 2 })
    expect(mergeSteps([a, c], b).map((s) => s.id)).toEqual(['a', 'b', 'c'])
    expect(mergeSteps([], a)).toEqual([a])
  })

  it('replaces a step with the same id in place (a highlight change)', () => {
    const a = makeStep({ id: 'a', turn: 1 })
    const b = makeStep({ id: 'b', turn: 2 })
    const next = mergeSteps([a, b], { ...a, highlight: true })
    expect(next.map((s) => [s.id, s.highlight])).toEqual([
      ['a', true],
      ['b', false],
    ])
  })
})

describe('deliverableStatus', () => {
  it('is done when the output has a section for it with at least one item', () => {
    const run = makeRun({
      deliverables: ['palette', 'type', 'layout'],
      output: {
        title: 'Out',
        sections: [
          { deliverable: 'palette', items: [{ item_id: 'i1', why: 'warm' }] },
          { deliverable: 'type', items: [] },
        ],
        note_ids: [],
      },
    })
    expect(deliverableStatus(run)).toEqual([
      { name: 'palette', done: true },
      { name: 'type', done: false },
      { name: 'layout', done: false },
    ])
  })

  it('is all open without an output', () => {
    expect(deliverableStatus(makeRun({ deliverables: ['palette'] }))).toEqual([{ name: 'palette', done: false }])
  })
})

describe('toolCall', () => {
  it('shows the call with its args, leaving out say and highlight', () => {
    expect(toolCall(makeStep({ tool: 'add_note', args: { text: 'hi', x: 2, say: 'Adding', highlight: true } }))).toBe(
      'add_note(text="hi", x=2)',
    )
  })

  it('truncates the args to 60 characters', () => {
    const line = toolCall(makeStep({ tool: 'add_note', args: { text: 'a'.repeat(100) } }))
    expect(line).toBe(`add_note(${`text="${'a'.repeat(100)}"`.slice(0, 60)}…)`)
  })
})

describe('mergeFetched', () => {
  it('keeps cached steps the fetched run does not have yet; the fetched copy wins for the rest', () => {
    const a = makeStep({ id: 'a', turn: 1 })
    const b = makeStep({ id: 'b', turn: 2 })
    const fresh = { ...makeRun({ status: 'done' }), steps: [{ ...a, highlight: true }] }
    const held = { ...makeRun(), steps: [a, b] }
    const out = mergeFetched(fresh, held)
    expect(out.status).toBe('done')
    expect(out.steps.map((s) => [s.id, s.highlight])).toEqual([
      ['a', true],
      ['b', false],
    ])
    expect(mergeFetched(fresh, undefined)).toBe(fresh)
  })
})
