import { describe, expect, it } from 'vitest'
import type { BoardProfile } from '../api'
import { inferredDomain } from './domains'

const withVotes = (votes: Record<string, number>) => ({ domain_votes: { votes } }) as unknown as BoardProfile

describe('inferredDomain', () => {
  it('names the domain most of the board votes for', () => {
    expect(inferredDomain(withVotes({ watch: 0.8, ui: 0.1 }))).toBe('watch')
  })

  it('names nothing when the top domain has under half the board (the rest fit no domain)', () => {
    expect(inferredDomain(withVotes({ fashion: 0.24 }))).toBeNull()
    expect(inferredDomain(withVotes({ watch: 0.5 }))).toBeNull()
  })

  it('names nothing without votes', () => {
    expect(inferredDomain(undefined)).toBeNull()
    expect(inferredDomain(withVotes({}))).toBeNull()
  })
})
