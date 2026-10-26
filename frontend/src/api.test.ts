import { describe, expect, it } from 'vitest'
import { apiOrigin } from './api'

describe('apiOrigin', () => {
  it('is empty (same origin, dev proxy) when VITE_API_URL is unset or blank', () => {
    expect(apiOrigin(undefined)).toBe('')
    expect(apiOrigin('  ')).toBe('')
  })

  it('drops trailing slashes so paths join cleanly', () => {
    expect(apiOrigin('https://user-dle.hf.space/')).toBe('https://user-dle.hf.space')
    expect(apiOrigin('https://api.example.com//')).toBe('https://api.example.com')
  })
})
