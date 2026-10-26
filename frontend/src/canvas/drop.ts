import type { Point, UploadOrigin } from '../api'
import { toCanvasPoint, type View } from './geometry'

export type UploadAt = (files: File[], at: Point, origin: UploadOrigin) => void

export interface DropInput {
  clientX: number
  clientY: number
  containerRect: { left: number; top: number }
  view: View
  files: File[]
}

/** Files dropped on the canvas land where they were dropped, in canvas coordinates. */
export function handleDrop(input: DropInput, upload: UploadAt): void {
  if (input.files.length === 0) return
  const pointer = {
    x: input.clientX - input.containerRect.left,
    y: input.clientY - input.containerRect.top,
  }
  upload(input.files, toCanvasPoint(pointer, input.view), 'drop')
}
