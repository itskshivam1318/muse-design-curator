import { describe, expect, it } from 'vitest'
import type { AttributeSpec, ItemAttribute, RunSummary } from '../api'
import fixtureJson from '../../../backend/tests/fixtures/protected_defaults.json'
import { makeProfile } from '../test/fixtures'
import {
  barState,
  canNudge,
  compareDiff,
  modesFor,
  nudgeTarget,
  orderProtected,
  defaultSelection,
  originLabel,
  preflightSentence,
  protectAll,
  progressText,
  shortfallText,
  sourceStatusLines,
  sortTargets,
} from './logic'

interface FixtureAttr { key: string; part?: string; value?: unknown; status?: ItemAttribute['status']; enabled?: boolean }
const fixture = fixtureJson as { cases: any[] }

function attr(key: string, value: ItemAttribute['value'], over: Partial<ItemAttribute> = {}): ItemAttribute {
  return {
    key, label: key.replace(/_/g, ' '), category: 'c', kind: 'enum', part: null, value,
    confidence: 0.9, status: 'extracted', source: 'model', enabled: true, ...over,
  }
}

const ordinal: AttributeSpec = { key: 'legibility', label: 'Legibility', category: 'dial', kind: 'ordinal', scale: ['low', 'medium', 'high'] }
const number: AttributeSpec = { key: 'diameter', label: 'Case diameter', category: 'case', kind: 'number', unit: 'mm', min: 30, max: 46, tolerance: 1 }

describe('nudge', () => {
  it('nudge only offered for ordinal/number', () => {
    expect(canNudge('ordinal')).toBe(true)
    expect(canNudge('number')).toBe(true)
    for (const k of ['enum', 'boolean', 'color', 'text', 'shape'] as const) expect(canNudge(k)).toBe(false)
    expect(modesFor('enum')).toEqual(['explore', 'prefer', 'avoid'])
    expect(modesFor('ordinal')).toEqual(['explore', 'prefer', 'avoid', 'nudge'])
  })

  it('computes the ordinal target step and refuses past the scale edge', () => {
    expect(nudgeTarget(ordinal, 'medium', 'more', 1)).toEqual({ ok: true, value: 'high', index: 2 })
    expect(nudgeTarget(ordinal, 'medium', 'less', 1)).toEqual({ ok: true, value: 'low', index: 0 })
    expect(nudgeTarget(ordinal, 'medium', 'more', 2).ok).toBe(false)
    expect(nudgeTarget(ordinal, 'high', 'more', 1).ok).toBe(false)
    expect(nudgeTarget(ordinal, null, 'more', 1).ok).toBe(false)
  })

  it('steps numbers by twice the tolerance within min/max', () => {
    expect(nudgeTarget(number, 40, 'more', 1)).toEqual({ ok: true, value: 42, index: null })
    expect(nudgeTarget(number, 40, 'less', 2)).toEqual({ ok: true, value: 36, index: null })
    expect(nudgeTarget(number, 45, 'more', 1).ok).toBe(false)
  })
})

describe('preflight sentence', () => {
  it('preflight sentence lists target, mode and protected', () => {
    const s = preflightSentence({
      targetLabel: 'Dial colour', mode: 'prefer', values: ['navy', 'royal_blue'],
      protectedLabels: ['Case finish', 'Strap material', 'Legibility'],
    })
    expect(s).toBe('Prefer Dial colour navy or royal blue, keeping Case finish, Strap material and Legibility unchanged.')
  })

  it('words explore, avoid and nudge, and an empty protected list', () => {
    expect(preflightSentence({ targetLabel: 'Dial colour', mode: 'explore', current: 'black', protectedLabels: ['Case finish'] }))
      .toBe('Explore Dial colour away from black, keeping Case finish unchanged.')
    expect(preflightSentence({ targetLabel: 'Strap', mode: 'avoid', values: ['gold'], protectedLabels: [] }))
      .toBe('Avoid Strap gold, with nothing protected.')
    expect(preflightSentence({
      targetLabel: 'Legibility', mode: 'nudge', nudge: { direction: 'more', steps: 1 },
      current: 'medium', target: 'high', protectedLabels: ['A', 'B'],
    })).toBe('Nudge Legibility more by 1 step (medium → high), keeping A and B unchanged.')
  })
})

describe('default protections', () => {
  it('matches the backend for every case in the shared fixture', () => {
    for (const c of fixture.cases) {
      const attrs = c.attrs.map((a: FixtureAttr) =>
        attr(a.key, 'value' in a ? (a.value as ItemAttribute['value']) : 'x', {
          part: a.part ?? null, status: a.status ?? 'extracted', enabled: a.enabled ?? true,
        }),
      )
      const signals = c.signals.map((s: { key: string; consistency: number; n_known: number }) => ({
        label: s.key, kind: 'enum', modal_value: 'v', ...s,
      }))
      const rows = orderProtected(attrs, c.target, signals.length ? makeProfile({ signals }) : null)
      expect(
        rows.map((r) => ({ key: r.key, is_board_signal: r.isBoardSignal, preselected: r.preselected, reason: r.reason })),
        c.name,
      ).toEqual(c.expected)
    }
  })

  it('pre-selects exactly the preselected rows, and Protect all selects every chip', () => {
    const attrs = [attr('t', 'y', { part: 'p' }), attr('a', 'x', { part: 'p' }), attr('b', 'x'), attr('c', 'x')]
    const rows = orderProtected(attrs, 't', null)
    expect([...defaultSelection(rows)]).toEqual(['a'])
    expect([...protectAll(rows)]).toEqual(['a', 'b', 'c'])
  })

  it('never proposes the target or unknown values', () => {
    const rows = orderProtected([attr('t', 'y'), attr('u', null), attr('k', 'x')], 't', null)
    expect(rows.map((r) => r.key)).toEqual(['k'])
  })
})

describe('target list', () => {
  it('puts tensions first, then lens order', () => {
    const lens = [{ key: 'a' }, { key: 'b' }, { key: 'c' }].map((x) => ({ ...x, label: x.key, category: 'c', kind: 'enum' }))
    const profile = makeProfile({ tensions: [{ key: 'c', label: 'c', values: ['p', 'q'], shares: [0.5, 0.5] }] })
    expect(sortTargets(lens, profile).map((a) => a.key)).toEqual(['c', 'a', 'b'])
  })
})

describe('candidate state', () => {
  it('maps validated to blue, uncertain to amber, everything else to no bar', () => {
    expect(barState('validated')).toBe('validated')
    expect(barState('uncertain')).toBe('uncertain')
    expect(barState('rejected')).toBeNull()
  })
})

describe('shortfall', () => {
  const summary: RunSummary = {
    pool_size: 20, excluded: {}, validated: 3, uncertain: 2, rejected: 5, returned: 3,
    shortfall: [
      { code: 'target_not_met', count: 2, message: '2 did not deliver the Dial colour change you asked for' },
      { code: 'protected_changed', count: 7, message: '7 changed a protected attribute (Strap material)' },
    ],
  }
  it('explains fewer than six and names the most common reason', () => {
    const t = shortfallText(summary)
    expect(t.link).toBe('Why only 3?')
    expect(t.headline).toBe('3 of 6 found.')
    expect(t.lines).toEqual(summary.shortfall!.map((l) => l.message))
    expect(t.mostCommon).toBe('7 changed a protected attribute (Strap material)')
  })
  it('has no link when six came back', () => {
    expect(shortfallText({ ...summary, returned: 6, shortfall: undefined }).link).toBeNull()
  })
})

describe('compare', () => {
  it('compare shows only differing attributes', () => {
    const rows = compareDiff([
      { itemId: 'i1', attributes: [attr('a', 'x'), attr('b', 'same'), attr('c', 3, { kind: 'number' })] },
      { itemId: 'i2', attributes: [attr('a', 'y'), attr('b', 'same'), attr('c', 3, { kind: 'number' })] },
      { itemId: 'i3', attributes: [attr('a', 'x'), attr('b', 'same')] },
    ])
    expect(rows.map((r) => r.key)).toEqual(['a', 'c'])
    expect(rows[0].values).toEqual(['x', 'y', 'x'])
    expect(rows[1].values).toEqual([3, 3, null])
  })
})

describe('live search copy', () => {
  it('names the sources being searched and the running count', () => {
    const live = { sources: {}, searching: ['commons', 'met', 'aic'], found: 23 }
    expect(progressText('searching', 0, 0, live)).toBe('Searching Wikimedia Commons, the Met, … (found 23)')
    expect(progressText('searching', 0, 0, { sources: {}, searching: ['commons'], found: 0 })).toBe('Searching Wikimedia Commons')
    expect(progressText('searching', 0, 0, { sources: { openverse: 'ok', met: 'failed' }, found: 5 })).toBe(
      'Searching Openverse, the Met (found 5)',
    )
    expect(progressText('searching')).toBe('Searching')
  })
  it('keeps the old copy when live search is off, then counts checks', () => {
    expect(progressText('retrieving')).toBe('Finding candidates')
    expect(progressText('validating', 8, 16, { sources: { commons: 'ok' }, found: 23 })).toBe('Checking 8 of 16')
  })
  it('lists each source with its status', () => {
    expect(sourceStatusLines({ queries: [], found: 12, kept: 2, sources: { commons: 'ok', openverse: 'failed', met: 'timeout' } })).toEqual([
      'Wikimedia Commons: searched',
      "Openverse: didn't respond",
      'the Met: timed out',
    ])
    expect(sourceStatusLines(undefined)).toEqual([])
  })
  it('labels where a candidate came from', () => {
    expect(originLabel({ origin: 'live', source: 'commons' })).toBe('Found live on Wikimedia Commons')
    expect(originLabel({ origin: 'live', source: 'newsite' })).toBe('Found live on newsite')
    expect(originLabel({ origin: 'corpus', source: 'commons' })).toBe('From your library')
    expect(originLabel({})).toBe('From your library')
  })
})
