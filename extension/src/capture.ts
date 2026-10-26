// Pure capture helpers shared by the content script, background worker and popup.

export interface Rect { x: number; y: number; width: number; height: number }
export interface Viewport { width: number; height: number }
export interface Crop { sx: number; sy: number; sw: number; sh: number }

/** Element rect (CSS px) -> pixel crop of a captureVisibleTab bitmap, clamped to the viewport. */
export function cropRect(rect: Rect, dpr: number, viewport: Viewport): Crop | null {
  const x0 = Math.max(0, rect.x)
  const y0 = Math.max(0, rect.y)
  const x1 = Math.min(viewport.width, rect.x + rect.width)
  const y1 = Math.min(viewport.height, rect.y + rect.height)
  if (x1 <= x0 || y1 <= y0) return null
  return {
    sx: Math.round(x0 * dpr),
    sy: Math.round(y0 * dpr),
    sw: Math.round((x1 - x0) * dpr),
    sh: Math.round((y1 - y0) * dpr),
  }
}

export interface PageImage {
  imageUrl: string | null
  title: string | null
  canonicalUrl: string | null
}

const MIN_SIDE = 256

function meta(doc: Document, selector: string): string | null {
  const v = doc.querySelector(selector)?.getAttribute('content')?.trim()
  return v ? v : null
}

function absolute(doc: Document, url: string | null): string | null {
  if (!url) return null
  try {
    return new URL(url, doc.baseURI).href
  } catch {
    return null
  }
}

function renderedSize(img: HTMLImageElement): [number, number] {
  const r = img.getBoundingClientRect()
  if (r.width && r.height) return [r.width, r.height]
  return [img.width || img.naturalWidth, img.height || img.naturalHeight]
}

/** og:image / og:title / canonical, falling back to the largest <img> (shortest side >= 256). */
export function pickPageImage(
  doc: Document,
  sizeOf: (img: HTMLImageElement) => [number, number] = renderedSize,
): PageImage {
  let imageUrl = absolute(doc, meta(doc, 'meta[property="og:image"]'))
  if (!imageUrl) {
    let best = 0
    for (const img of Array.from(doc.querySelectorAll('img'))) {
      const [w, h] = sizeOf(img)
      if (Math.min(w, h) >= MIN_SIDE && w * h > best) {
        best = w * h
        imageUrl = img.currentSrc || img.src || null
      }
    }
  }
  const title = meta(doc, 'meta[property="og:title"]') ?? (doc.title.trim() || null)
  const canonicalUrl = absolute(doc, doc.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null)
  return { imageUrl, title, canonicalUrl }
}

interface SiteRule { host: RegExp; selectors: string[]; skip: string[] }

const SITES: SiteRule[] = [
  {
    host: /(^|\.)instagram\.com$/,
    selectors: ['header a[href^="/"]'],
    skip: ['p', 'reel', 'reels', 'explore', 'accounts', 'stories'],
  },
  {
    host: /(^|\.)pinterest\.[a-z.]+$/,
    selectors: [
      '[data-test-id="pin-closeup-creator"] a[href^="/"]',
      '[data-test-id="creator-profile-name"] a[href^="/"]',
    ],
    skip: ['pin', 'search', 'ideas', 'today'],
  },
]

function handleFromHref(href: string, skip: string[]): string | null {
  const seg = href.split(/[?#]/)[0].split('/').filter(Boolean)[0]
  if (!seg || skip.includes(seg)) return null
  return `@${seg}`
}

/** The creator handle the page itself shows; null when absent. Never guessed. */
export function readCreatorHandle(doc: Document, hostname: string): string | null {
  for (const site of SITES) {
    if (!site.host.test(hostname)) continue
    for (const sel of site.selectors) {
      const href = doc.querySelector(sel)?.getAttribute('href')
      const handle = href ? handleFromHref(href, site.skip) : null
      if (handle) return handle
    }
  }
  return meta(doc, 'meta[name="author"]') ?? meta(doc, 'meta[property="article:author"]')
}

export type CaptureKind = 'image' | 'video'

export interface CapturePayload {
  image_b64?: string
  frames_b64?: string[]
  source_url: string
  page_url: string
  page_title: string
  creator_handle?: string
  kind: CaptureKind
  captured_at: string
}

export function buildCapture(args: {
  kind: CaptureKind
  imageB64?: string
  framesB64?: string[]
  sourceUrl: string
  pageUrl: string
  pageTitle: string
  creatorHandle: string | null
  now?: Date
}): CapturePayload {
  const out: CapturePayload = {
    source_url: args.sourceUrl,
    page_url: args.pageUrl,
    page_title: args.pageTitle,
    kind: args.kind,
    captured_at: (args.now ?? new Date()).toISOString(),
  }
  if (args.framesB64) out.frames_b64 = args.framesB64
  if (args.imageB64) out.image_b64 = args.imageB64
  if (args.creatorHandle) out.creator_handle = args.creatorHandle
  return out
}

export function dataUrlToB64(dataUrl: string): string {
  return dataUrl.slice(dataUrl.indexOf(',') + 1)
}

export async function blobToB64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(bin)
}

/** Fetch an image URL; null when the page/CDN blocks it (caller falls back to a screenshot crop). */
export async function fetchImageB64(url: string, fetchFn: typeof fetch = fetch): Promise<string | null> {
  try {
    const res = await fetchFn(url)
    if (!res.ok) return null
    const blob = await res.blob()
    if (!blob.type.startsWith('image/')) return null
    return await blobToB64(blob)
  } catch {
    return null
  }
}
