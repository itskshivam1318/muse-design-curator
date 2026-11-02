import { afterEach, describe, expect, it } from 'vitest'
import { closeRail, noteLensProposal, openRail, railStore, setTool, toolForKey, toolStore } from './tools'

afterEach(() => setTool('select'))

describe('toolForKey', () => {
  it('maps n to note and Escape to select', () => {
    expect(toolForKey('n')).toBe('note')
    expect(toolForKey('N')).toBe('note')
    expect(toolForKey('Escape')).toBe('select')
  })

  it('ignores every other key, including a (the old Axis tool) and v', () => {
    for (const k of ['a', 'v', 'i', 'x', 'f', 'Delete', ' ', 'Enter']) expect(toolForKey(k)).toBeNull()
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

describe('rail state', () => {
  afterEach(() => closeRail())

  it('records why a panel opened, and closing clears it', () => {
    openRail('search')
    expect(railStore.get()).toEqual({ open: 'search', reason: 'user' })
    openRail('library', 'auto')
    expect(railStore.get().reason).toBe('auto')
    closeRail()
    expect(railStore.get().open).toBeNull()
  })

  it('a new lens proposal opens Library when nothing is open', () => {
    noteLensProposal(true)
    expect(railStore.get()).toEqual({ open: 'library', reason: 'auto' })
  })

  it('a new lens proposal leaves another open panel alone', () => {
    openRail('search')
    noteLensProposal(true)
    expect(railStore.get()).toEqual({ open: 'search', reason: 'user' })
  })
})
