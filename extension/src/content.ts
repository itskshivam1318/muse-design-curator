// Injected on demand (chrome.scripting.executeScript + activeTab). Reads the DOM only; never
// scrolls, crawls or downloads anything.
import { pickPageImage, readCreatorHandle, type Rect } from './capture'

export interface PageContext {
  rect: Rect | null
  dpr: number
  viewport: { width: number; height: number }
  pageUrl: string
  pageTitle: string
  creatorHandle: string | null
  imageUrl?: string | null
  ok?: boolean
}

type Msg =
  | { type: 'dle-image'; srcUrl: string }
  | { type: 'dle-video-prepare'; srcUrl?: string }
  | { type: 'dle-video-seek' }
  | { type: 'dle-page' }

function rectOf(el: Element | null): Rect | null {
  if (!el) return null
  const r = el.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height }
}

function context(rect: Rect | null, extra: Partial<PageContext> = {}): PageContext {
  return {
    rect,
    dpr: window.devicePixelRatio || 1,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    pageUrl: location.href,
    pageTitle: document.title,
    creatorHandle: readCreatorHandle(document, location.hostname),
    ...extra,
  }
}

function visibleArea(el: Element): number {
  const r = el.getBoundingClientRect()
  const w = Math.min(window.innerWidth, r.right) - Math.max(0, r.left)
  const h = Math.min(window.innerHeight, r.bottom) - Math.max(0, r.top)
  return w > 0 && h > 0 ? w * h : 0
}

function largestVisible<T extends Element>(els: T[]): T | null {
  return els.reduce<T | null>((best, el) => (visibleArea(el) > (best ? visibleArea(best) : 0) ? el : best), null)
}

let activeVideo: HTMLVideoElement | null = null

function findVideo(srcUrl?: string): HTMLVideoElement | null {
  const videos = Array.from(document.querySelectorAll('video'))
  const bySrc = srcUrl && !srcUrl.startsWith('blob:') ? videos.find((v) => v.currentSrc === srcUrl) : null
  return bySrc ?? videos.find((v) => !v.paused && visibleArea(v) > 0) ?? largestVisible(videos)
}

function seekOneSecond(video: HTMLVideoElement): Promise<boolean> {
  return new Promise((resolve) => {
    const target = video.currentTime + 1
    if (Number.isFinite(video.duration) && target > video.duration) return resolve(false)
    const timer = setTimeout(() => done(false), 2000)
    const done = (ok: boolean) => {
      clearTimeout(timer)
      video.removeEventListener('seeked', onSeeked)
      resolve(ok)
    }
    const onSeeked = () => done(Math.abs(video.currentTime - target) < 0.5)
    video.addEventListener('seeked', onSeeked)
    try {
      video.currentTime = target
    } catch {
      done(false)
    }
  })
}

async function handle(msg: Msg): Promise<PageContext> {
  switch (msg.type) {
    case 'dle-image': {
      const imgs = Array.from(document.querySelectorAll('img'))
      const hit = imgs.filter((i) => i.currentSrc === msg.srcUrl || i.src === msg.srcUrl)
      return context(rectOf(largestVisible(hit) ?? hit[0] ?? null))
    }
    case 'dle-video-prepare': {
      activeVideo = findVideo(msg.srcUrl)
      activeVideo?.pause()
      return context(rectOf(activeVideo), { ok: !!activeVideo })
    }
    case 'dle-video-seek': {
      if (!activeVideo) return context(null, { ok: false })
      activeVideo.pause()
      const ok = await seekOneSecond(activeVideo)
      return context(rectOf(activeVideo), { ok })
    }
    case 'dle-page': {
      const page = pickPageImage(document)
      const img = page.imageUrl
        ? Array.from(document.querySelectorAll('img')).find((i) => (i.currentSrc || i.src) === page.imageUrl)
        : null
      return context(rectOf(img ?? null), {
        imageUrl: page.imageUrl,
        pageTitle: page.title ?? document.title,
        pageUrl: page.canonicalUrl ?? location.href,
      })
    }
  }
}

const w = window as unknown as { __dleContent?: boolean }
if (!w.__dleContent) {
  w.__dleContent = true
  chrome.runtime.onMessage.addListener((msg: Msg, _sender, sendResponse) => {
    if (!msg || typeof msg.type !== 'string' || !msg.type.startsWith('dle-')) return false
    handle(msg).then(sendResponse, () => sendResponse(null))
    return true
  })
}
