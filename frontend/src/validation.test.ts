import { describe, expect, it } from 'vitest'
import { MiB, partitionFiles, validateFile } from './validation'

function fakeFile(name: string, type: string, size: number): File {
  const f = new File(['x'], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

describe('validateFile', () => {
  it('accepts supported images up to 10 MiB and videos up to 100 MiB', () => {
    expect(validateFile(fakeFile('a.jpg', 'image/jpeg', 10 * MiB)).ok).toBe(true)
    expect(validateFile(fakeFile('a.gif', 'image/gif', 1)).ok).toBe(true)
    expect(validateFile(fakeFile('a.mov', 'video/quicktime', 100 * MiB)).ok).toBe(true)
    expect(validateFile(fakeFile('a.webm', '', 5)).ok).toBe(true) // extension fallback
  })

  it('rejects oversize and unsupported files with a per-file message', () => {
    const big = validateFile(fakeFile('a.png', 'image/png', 10 * MiB + 1))
    expect(big).toEqual({ ok: false, message: 'a.png is larger than 10 MiB' })
    const vid = validateFile(fakeFile('v.mp4', 'video/mp4', 100 * MiB + 1))
    expect(vid.ok).toBe(false)
    const svg = validateFile(fakeFile('a.svg', 'image/svg+xml', 10))
    expect(svg).toEqual({ ok: false, message: 'a.svg is not a supported type (JPEG, PNG, WebP, GIF, MP4, MOV, WebM)' })
  })

  it('partitions a batch', () => {
    const { valid, rejected } = partitionFiles([
      fakeFile('a.png', 'image/png', 1),
      fakeFile('b.txt', 'text/plain', 1),
    ])
    expect(valid.map((f) => f.name)).toEqual(['a.png'])
    expect(rejected.map((r) => r.filename)).toEqual(['b.txt'])
  })
})
