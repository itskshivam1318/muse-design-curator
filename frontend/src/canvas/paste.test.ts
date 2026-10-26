import { describe, expect, it, vi } from 'vitest'
import { handlePaste } from './paste'

describe('paste', () => {
  it('paste URL calls ingest link', async () => {
    const addLink = vi.fn().mockResolvedValue(undefined)
    const uploadFiles = vi.fn()
    const handled = await handlePaste(
      { files: [], text: '  https://example.com/p/1  ' },
      { center: { x: 10, y: 20 }, addLink, uploadFiles },
    )
    expect(handled).toBe(true)
    expect(addLink).toHaveBeenCalledWith('https://example.com/p/1', { x: 10, y: 20 })
    expect(uploadFiles).not.toHaveBeenCalled()
  })

  it('pasted images upload at the viewport centre', async () => {
    const addLink = vi.fn()
    const uploadFiles = vi.fn()
    const f = new File(['x'], 'image.png', { type: 'image/png' })
    await handlePaste({ files: [f], text: '' }, { center: { x: 1, y: 2 }, addLink, uploadFiles })
    expect(uploadFiles).toHaveBeenCalledWith([f], { x: 1, y: 2 }, 'paste')
    expect(addLink).not.toHaveBeenCalled()
  })

  it('ignores plain text and non-http urls', async () => {
    const addLink = vi.fn()
    const deps = { center: { x: 0, y: 0 }, addLink, uploadFiles: vi.fn() }
    expect(await handlePaste({ files: [], text: 'hello world' }, deps)).toBe(false)
    expect(await handlePaste({ files: [], text: 'javascript:alert(1)' }, deps)).toBe(false)
    expect(await handlePaste({ files: [], text: 'ftp://x.test/a' }, deps)).toBe(false)
    expect(addLink).not.toHaveBeenCalled()
  })
})
