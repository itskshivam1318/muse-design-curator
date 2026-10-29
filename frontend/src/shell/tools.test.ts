import { afterEach, describe, expect, it } from 'vitest'
import { setTool, toolForKey, toolStore } from './tools'

afterEach(() => setTool('select'))

describe('toolForKey', () => {
  it('maps n to note, a to axis and Escape to select', () => {
    expect(toolForKey('n', { explore: true })).toBe('note')
    expect(toolForKey('N', { explore: true })).toBe('note')
    expect(toolForKey('a', { explore: true })).toBe('axis')
    expect(toolForKey('Escape', { explore: true })).toBe('select')
  })

  it('has no axis tool when explore is off', () => {
    expect(toolForKey('a', { explore: false })).toBeNull()
    expect(toolForKey('n', { explore: false })).toBe('note')
    expect(toolForKey('Escape', { explore: false })).toBe('select')
  })

  it('ignores every other key, including v (Explore)', () => {
    for (const k of ['v', 'i', 'x', 'f', 'Delete', ' ', 'Enter']) expect(toolForKey(k, { explore: true })).toBeNull()
  })
})

describe('toolStore', () => {
  it('starts on select and notifies on change', () => {
    expect(toolStore.get()).toBe('select')
    let calls = 0
    const off = toolStore.subscribe(() => calls++)
    setTool('note')
    expect(toolStore.get()).toBe('note')
    setTool('note') // no change, no notification
    off()
    expect(calls).toBe(1)
  })
})
