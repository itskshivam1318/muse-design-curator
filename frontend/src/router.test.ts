import { describe, expect, it } from 'vitest'
import { matchRoute } from './router'

describe('matchRoute', () => {
  it('maps / to the board list and /boards/:id to a board', () => {
    expect(matchRoute('/')).toEqual({ name: 'boards' })
    expect(matchRoute('/boards/board_01H')).toEqual({ name: 'board', id: 'board_01H' })
    expect(matchRoute('/boards/x/')).toEqual({ name: 'board', id: 'x' })
    expect(matchRoute('/nope')).toEqual({ name: 'not-found' })
  })
})
