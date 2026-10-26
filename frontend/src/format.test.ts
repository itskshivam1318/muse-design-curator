import { describe, expect, it } from 'vitest'
import { safeExternalUrl } from './format'

describe('safeExternalUrl', () => {
  it('keeps absolute http and https URLs', () => {
    expect(safeExternalUrl('https://example.org/p?q=1')).toBe('https://example.org/p?q=1')
    expect(safeExternalUrl('http://example.org')).toBe('http://example.org')
  })
  it('drops other schemes, relative, malformed and empty values', () => {
    for (const u of ['javascript:alert(1)', 'JavaScript:alert(1)', ' javascript:alert(1)', 'data:text/html,<b>x</b>',
      'vbscript:x', 'file:///etc/passwd', '/relative/path', '//example.org/x', 'not a url', '', null, undefined]) {
      expect(safeExternalUrl(u as string | null | undefined)).toBeNull()
    }
  })
})
