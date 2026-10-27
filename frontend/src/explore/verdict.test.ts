import { describe, expect, it } from 'vitest'
import { verdictText } from './verdict'

const yes = { answer: 'yes' as const, confidence: 0.9, note: '' }

describe('verdictText', () => {
  it('is pending while unchecked', () => {
    expect(verdictText(null, 'Colour', 'Navy')).toEqual({ text: 'Checking…', tone: 'pending' })
  })
  it('yes with nothing drifted is ok', () => {
    expect(verdictText({ target: yes, kept: 3, of: 4, drifted: [] }, 'Colour', 'Navy')).toEqual({
      text: 'Colour → Navy ✓ · 3 of 4 kept',
      tone: 'ok',
    })
  })
  it('yes with drift warns and lists labels', () => {
    const labels = new Map([['strap', 'Strap']])
    expect(verdictText({ target: yes, kept: 2, of: 4, drifted: ['strap', 'dial'] }, 'Colour', 'Navy', labels)).toEqual({
      text: 'Colour → Navy ✓ · 2 of 4 kept · drifted: Strap, dial',
      tone: 'warn',
    })
  })
  it('adds unclear count only when positive', () => {
    expect(verdictText({ target: yes, kept: 3, of: 3, unknown: 2 }, 'Colour', 'Navy').text).toBe(
      'Colour → Navy ✓ · 3 of 3 kept · 2 unclear',
    )
  })
  it('no, unclear and error', () => {
    expect(verdictText({ target: { ...yes, answer: 'no' } }, 'Colour', 'Navy')).toEqual({
      text: "Colour didn't change to Navy",
      tone: 'warn',
    })
    expect(verdictText({ target: { ...yes, answer: 'unclear' } }, 'Colour', 'Navy')).toEqual({
      text: 'Colour: unclear',
      tone: 'warn',
    })
    expect(verdictText({ error: 'boom' }, 'Colour', 'Navy')).toEqual({ text: 'Check failed', tone: 'error' })
  })
})
