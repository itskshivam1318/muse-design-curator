import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { expect, type Locator, type Page } from '@playwright/test'
import { API_URL } from './ports.ts'

/** Files written by backend/scripts/e2e_prepare.py (also served by the fixture site). */
export const SITE_DIR = resolve(import.meta.dirname, '../../../data/e2e/site')
export const sitePath = (name: string) => join(SITE_DIR, name)

export interface ApiItem {
  id: string
  kind: string
  role: string
  parse_status: string
  original_filename: string | null
  page_title: string | null
  page_url: string | null
  parent_item_id: string | null
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api${path}`, init)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

export const boardItems = (boardId: string) =>
  apiJson<{ items: ApiItem[] }>(`/boards/${boardId}/items`).then((r) => r.items)

export function boardIdOf(page: Page): string {
  const m = /\/boards\/([^/?#]+)/.exec(page.url())
  if (!m) throw new Error(`not on a board page: ${page.url()}`)
  return decodeURIComponent(m[1])
}

/** The canvas region announces its item count in its accessible name. */
export const canvas = (page: Page) => page.getByRole('region', { name: /^Board canvas/ })

export async function expectItemCount(page: Page, n: number): Promise<void> {
  await expect(canvas(page)).toHaveAccessibleName(new RegExp(`^Board canvas, ${n} items?,`))
}

/** The screen-reader list mirrors every canvas item; its buttons select them (keyboard path). */
export function itemButton(page: Page, name: string | RegExp): Locator {
  return page.getByRole('list', { name: 'Items on this board' }).getByRole('button', { name })
}

export async function selectItem(page: Page, name: string | RegExp): Promise<void> {
  const btn = itemButton(page, name)
  await btn.focus()
  await page.keyboard.press('Enter')
  await expect(btn).toHaveAttribute('aria-pressed', 'true')
}

/** Simulate dropping files from the desktop onto the canvas (a real DataTransfer with File objects). */
export async function dropFiles(page: Page, target: Locator, paths: string[], mime = 'image/jpeg'): Promise<void> {
  const files = paths.map((p) => ({ name: p.split('/').pop()!, b64: readFileSync(p).toString('base64') }))
  const dataTransfer = await page.evaluateHandle(
    ({ files, mime }) => {
      const dt = new DataTransfer()
      for (const f of files) {
        const bytes = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0))
        dt.items.add(new File([bytes], f.name, { type: mime }))
      }
      return dt
    },
    { files, mime },
  )
  const box = await target.boundingBox()
  const at = box ? { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 } : {}
  await target.dispatchEvent('dragover', { dataTransfer, ...at })
  await target.dispatchEvent('drop', { dataTransfer, ...at })
}
