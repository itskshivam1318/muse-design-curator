/** Client-side mirror of the server's accepted inputs, so bad files fail before upload. */

export const MiB = 1024 * 1024

const IMAGE_TYPES: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/gif': 'gif',
}
const VIDEO_TYPES: Record<string, string> = {
  'video/mp4': 'mp4',
  'video/quicktime': 'mov',
  'video/webm': 'webm',
}
const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif'])
const VIDEO_EXT = new Set(['mp4', 'mov', 'webm'])

export const IMAGE_MAX = 10 * MiB
export const VIDEO_MAX = 100 * MiB
export const ACCEPT = [...Object.keys(IMAGE_TYPES), ...Object.keys(VIDEO_TYPES)].join(',')

export type Validation = { ok: true; kind: 'image' | 'video' } | { ok: false; message: string }

function kindOf(file: File): 'image' | 'video' | null {
  if (file.type in IMAGE_TYPES) return 'image'
  if (file.type in VIDEO_TYPES) return 'video'
  if (file.type) return null
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (IMAGE_EXT.has(ext)) return 'image'
  if (VIDEO_EXT.has(ext)) return 'video'
  return null
}

export function validateFile(file: File): Validation {
  const kind = kindOf(file)
  if (kind === null) {
    return {
      ok: false,
      message: `${file.name} is not a supported type (JPEG, PNG, WebP, GIF, MP4, MOV, WebM)`,
    }
  }
  const max = kind === 'image' ? IMAGE_MAX : VIDEO_MAX
  if (file.size > max) return { ok: false, message: `${file.name} is larger than ${max / MiB} MiB` }
  return { ok: true, kind }
}

export interface Rejected {
  filename: string
  message: string
}

export function partitionFiles(files: File[]): { valid: File[]; rejected: Rejected[] } {
  const valid: File[] = []
  const rejected: Rejected[] = []
  for (const f of files) {
    const v = validateFile(f)
    if (v.ok) valid.push(f)
    else rejected.push({ filename: f.name, message: v.message })
  }
  return { valid, rejected }
}
