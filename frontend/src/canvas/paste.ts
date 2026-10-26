import type { Point } from '../api'
import type { UploadAt } from './drop'

export interface PasteData {
  files: File[]
  text: string
}

export interface PasteDeps {
  center: Point
  uploadFiles: UploadAt
  addLink: (url: string, at: Point) => Promise<unknown>
}

export function asHttpUrl(text: string): string | null {
  const t = text.trim()
  if (!t || /\s/.test(t)) return null
  try {
    const u = new URL(t)
    return u.protocol === 'http:' || u.protocol === 'https:' ? t : null
  } catch {
    return null
  }
}

/** ⌘V on the board: pasted images upload, a pasted URL is ingested as a link. Both at the viewport centre. */
export async function handlePaste(data: PasteData, deps: PasteDeps): Promise<boolean> {
  if (data.files.length > 0) {
    deps.uploadFiles(data.files, deps.center, 'paste')
    return true
  }
  const url = asHttpUrl(data.text)
  if (!url) return false
  await deps.addLink(url, deps.center)
  return true
}

export function readClipboard(dt: DataTransfer | null): PasteData {
  if (!dt) return { files: [], text: '' }
  const files: File[] = []
  for (const it of Array.from(dt.items ?? [])) {
    if (it.kind === 'file') {
      const f = it.getAsFile()
      if (f) files.push(f)
    }
  }
  return { files, text: dt.getData('text/plain') ?? '' }
}
