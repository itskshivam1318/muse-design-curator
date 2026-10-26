import {
  blobToB64, buildCapture, cropRect, fetchImageB64, type CapturePayload,
} from './capture'
import type { PageContext } from './content'
import { loadSettings, postCapture, ApiError, type Settings } from './pair'

const BLOCKED_NOTICE = 'This page blocks image downloads. Captured a screenshot of the image instead.'
const MAX_EXTRA_FRAMES = 3
const CAPTURE_GAP_MS = 600 // captureVisibleTab is rate limited to about 2 calls per second

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'add-image', title: 'Add to board', contexts: ['image'] })
    chrome.contextMenus.create({ id: 'add-video', title: 'Add this video to board', contexts: ['video'] })
  })
})

async function inject(tabId: number): Promise<void> {
  await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] })
}

async function ask(tabId: number, msg: object): Promise<PageContext> {
  const reply = (await chrome.tabs.sendMessage(tabId, msg)) as PageContext | null
  if (!reply) throw new ApiError('Could not read this page. Reload it and try again.', 'CONTENT')
  return reply
}

/** Visible-tab screenshot cropped to the element rect x devicePixelRatio. Returns base64 PNG. */
async function screenshotCrop(windowId: number | undefined, ctx: PageContext): Promise<string> {
  if (!ctx.rect) throw new ApiError("Couldn't find that element on the page.", 'NO_RECT')
  const crop = cropRect(ctx.rect, ctx.dpr, ctx.viewport)
  if (!crop) throw new ApiError('Scroll it fully into view and try again.', 'OFFSCREEN')
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId ?? chrome.windows.WINDOW_ID_CURRENT, {
    format: 'png',
  })
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob())
  const canvas = new OffscreenCanvas(crop.sw, crop.sh)
  canvas.getContext('2d')!.drawImage(bitmap, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, crop.sw, crop.sh)
  const out = await canvas.convertToBlob({ type: 'image/png' })
  return blobToB64(out)
}

async function requireReady(boardId?: string | null): Promise<{ settings: Settings; boardId: string }> {
  const settings = await loadSettings()
  if (!settings.token) throw new ApiError('Pair the extension first: open it and enter the code shown in the app.', 'UNPAIRED')
  const id = boardId ?? settings.lastBoardId
  if (!id) throw new ApiError('Open the extension and choose a board first.', 'NO_BOARD')
  return { settings, boardId: id }
}

interface Outcome { notice?: string }

async function captureImage(tab: chrome.tabs.Tab, srcUrl: string): Promise<Outcome> {
  const { settings, boardId } = await requireReady()
  const tabId = tab.id!
  await inject(tabId)
  const ctx = await ask(tabId, { type: 'dle-image', srcUrl })
  let b64 = await fetchImageB64(srcUrl)
  let notice: string | undefined
  if (!b64) {
    b64 = await screenshotCrop(tab.windowId, ctx)
    notice = BLOCKED_NOTICE
  }
  await postCapture(settings, boardId, buildCapture({
    kind: 'image', imageB64: b64, sourceUrl: srcUrl, pageUrl: ctx.pageUrl,
    pageTitle: ctx.pageTitle, creatorHandle: ctx.creatorHandle,
  }))
  return { notice }
}

async function captureVideo(tab: chrome.tabs.Tab, srcUrl?: string): Promise<Outcome> {
  const { settings, boardId } = await requireReady()
  const tabId = tab.id!
  await inject(tabId)
  let ctx = await ask(tabId, { type: 'dle-video-prepare', srcUrl })
  if (!ctx.ok) throw new ApiError("Couldn't find the video on this page.", 'NO_VIDEO')
  const first = ctx
  const frames = [await screenshotCrop(tab.windowId, ctx)]
  for (let i = 0; i < MAX_EXTRA_FRAMES; i++) {
    ctx = await ask(tabId, { type: 'dle-video-seek' })
    if (!ctx.ok) break // the page blocks seeking: send what we have
    await sleep(CAPTURE_GAP_MS)
    try {
      frames.push(await screenshotCrop(tab.windowId, ctx))
    } catch {
      break
    }
  }
  const source = srcUrl && !srcUrl.startsWith('blob:') ? srcUrl : first.pageUrl
  await postCapture(settings, boardId, buildCapture({
    kind: 'video', framesB64: frames, sourceUrl: source, pageUrl: first.pageUrl,
    pageTitle: first.pageTitle, creatorHandle: first.creatorHandle,
  }))
  return {}
}

async function capturePage(tabId: number, boardId: string): Promise<Outcome> {
  const { settings } = await requireReady(boardId)
  await inject(tabId)
  const ctx = await ask(tabId, { type: 'dle-page' })
  if (!ctx.imageUrl) {
    throw new ApiError('This page has no preview image. Right-click an image on it to add that instead.', 'NO_IMAGE')
  }
  let b64 = await fetchImageB64(ctx.imageUrl)
  let notice: string | undefined
  if (!b64) {
    const tab = await chrome.tabs.get(tabId)
    b64 = await screenshotCrop(tab.windowId, ctx)
    notice = BLOCKED_NOTICE
  }
  const payload: CapturePayload = buildCapture({
    kind: 'image', imageB64: b64, sourceUrl: ctx.imageUrl, pageUrl: ctx.pageUrl,
    pageTitle: ctx.pageTitle, creatorHandle: ctx.creatorHandle,
  })
  await postCapture(settings, boardId, payload)
  return { notice }
}

async function flash(text: string, title: string): Promise<void> {
  await chrome.action.setBadgeText({ text })
  await chrome.action.setTitle({ title })
  setTimeout(() => void chrome.action.setBadgeText({ text: '' }), 6000)
}

async function fromMenu(run: () => Promise<Outcome>): Promise<void> {
  try {
    const out = await run()
    await flash('OK', out.notice ?? 'Added to your board')
  } catch (e) {
    await flash('!', (e as Error).message)
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.id) return
  if (info.menuItemId === 'add-image' && info.srcUrl) void fromMenu(() => captureImage(tab, info.srcUrl!))
  if (info.menuItemId === 'add-video') void fromMenu(() => captureVideo(tab, info.srcUrl))
})

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== 'add-page') return false
  capturePage(msg.tabId, msg.boardId).then(
    (out) => sendResponse({ ok: true, notice: out.notice }),
    (e: Error) => sendResponse({ ok: false, error: e.message }),
  )
  return true
})
