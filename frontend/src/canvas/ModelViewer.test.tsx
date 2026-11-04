import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeItem } from '../test/fixtures'

const loaded = vi.fn()
vi.mock('@google/model-viewer', () => {
  loaded()
  return {}
})
const { ModelViewer } = await import('./ModelViewer')

afterEach(cleanup)
const model = makeItem({ id: 'm1', kind: 'model', mime: 'model/gltf-binary', original_filename: 'chair.glb' })

describe('ModelViewer', () => {
  it('loads the viewer module lazily, once, and links the glb for download', async () => {
    expect(loaded).not.toHaveBeenCalled() // nothing imported until the viewer opens
    const { rerender } = render(<ModelViewer item={model} onClose={() => {}} />)
    await waitFor(() => expect(document.querySelector('model-viewer')).not.toBeNull())
    expect(loaded).toHaveBeenCalledTimes(1)
    const el = document.querySelector('model-viewer')!
    expect(el.getAttribute('src')).toContain('/items/m1/image?size=full')
    expect(el.hasAttribute('camera-controls')).toBe(true)
    const link = screen.getByRole('link', { name: 'Download .glb' })
    expect(link.getAttribute('href')).toContain('/items/m1/image?size=full')
    expect(link.getAttribute('download')).toBe('chair.glb')
    rerender(<ModelViewer item={model} onClose={() => {}} />)
    expect(loaded).toHaveBeenCalledTimes(1)
  })
})
