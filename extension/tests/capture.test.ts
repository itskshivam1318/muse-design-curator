// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from 'vitest'
import { cropRect, pickPageImage, readCreatorHandle } from '../src/capture'
import { renderPopup } from '../src/popup'
import { DEFAULTS, pairRequestBody } from '../src/pair'

describe('cropRect', () => {
  it('crop rect scales by devicePixelRatio', () => {
    const r = cropRect({ x: 10, y: 20, width: 100, height: 50 }, 2, { width: 800, height: 600 })
    expect(r).toEqual({ sx: 20, sy: 40, sw: 200, sh: 100 })
  })
  it('clamps to the viewport', () => {
    const r = cropRect({ x: -10, y: 550, width: 100, height: 100 }, 2, { width: 800, height: 600 })
    expect(r).toEqual({ sx: 0, sy: 1100, sw: 180, sh: 100 })
  })
  it('returns null when the rect is outside the viewport', () => {
    expect(cropRect({ x: 900, y: 0, width: 10, height: 10 }, 1, { width: 800, height: 600 })).toBeNull()
  })
})

function docOf(html: string): Document {
  return new DOMParser().parseFromString(html, 'text/html')
}

describe('pickPageImage', () => {
  it('reads og tags and canonical', () => {
    const d = docOf(`<head><meta property="og:image" content="https://x.test/a.jpg">
      <meta property="og:title" content="T"><link rel="canonical" href="https://x.test/c"></head>`)
    expect(pickPageImage(d)).toEqual({
      imageUrl: 'https://x.test/a.jpg', title: 'T', canonicalUrl: 'https://x.test/c',
    })
  })
  it('og parsing falls back to first large img', () => {
    const d = docOf(`<head><title>Doc</title></head><body>
      <img src="https://x.test/small.png" width="100" height="100">
      <img src="https://x.test/big.png" width="600" height="400"></body>`)
    const sizes: Record<string, [number, number]> = {
      'https://x.test/small.png': [100, 100], 'https://x.test/big.png': [600, 400],
    }
    const out = pickPageImage(d, (img) => sizes[img.src] ?? [0, 0])
    expect(out.imageUrl).toBe('https://x.test/big.png')
    expect(out.title).toBe('Doc')
    expect(out.canonicalUrl).toBeNull()
  })
  it('returns null image when nothing qualifies', () => {
    expect(pickPageImage(docOf('<body><img src="a.png"></body>'), () => [10, 10]).imageUrl).toBeNull()
  })
})

describe('readCreatorHandle', () => {
  it('handle selector returns null when absent (never guessed)', () => {
    expect(readCreatorHandle(docOf('<body><h1>@someone</h1></body>'), 'www.instagram.com')).toBeNull()
    expect(readCreatorHandle(docOf('<body></body>'), 'example.com')).toBeNull()
  })
  it('reads instagram header link', () => {
    const d = docOf('<body><header><a href="/natgeo/">natgeo</a></header></body>')
    expect(readCreatorHandle(d, 'www.instagram.com')).toBe('@natgeo')
  })
  it('reads pinterest attribution', () => {
    const d = docOf('<body><div data-test-id="pin-closeup-creator"><a href="/jane/">Jane</a></div></body>')
    expect(readCreatorHandle(d, 'nl.pinterest.com')).toBe('@jane')
  })
  it('falls back to meta author', () => {
    expect(readCreatorHandle(docOf('<head><meta name="author" content="Ada"></head>'), 'x.test')).toBe('Ada')
    expect(
      readCreatorHandle(docOf('<head><meta property="article:author" content="Bo"></head>'), 'x.test'),
    ).toBe('Bo')
  })
})

describe('popup', () => {
  let root: HTMLElement
  beforeEach(() => { root = document.createElement('div') })

  it('unpaired extension shows pairing screen', () => {
    renderPopup(root, { ...DEFAULTS, token: null }, { boards: [], status: null }, {} as never)
    expect(root.textContent).toContain('Pair with your board')
    expect(root.textContent).toContain('Enter the 6-digit code shown in the app')
    expect(root.querySelector('button#add-page')).toBeNull()
  })
  it('pairing screen shows the configured apiBase and the host_permissions note', () => {
    renderPopup(root, { ...DEFAULTS, apiBase: 'http://localhost:8000', token: null }, { boards: [], status: null }, {} as never)
    const note = root.querySelector('#api-note')
    expect(note?.textContent).toContain('http://localhost:8000')
    expect(note?.textContent).toContain(
      'This build talks to http://localhost:8000. To use another address, edit manifest.json host_permissions.',
    )
  })
  it('paired extension shows Add this page', () => {
    renderPopup(root, { ...DEFAULTS, token: 't' }, { boards: [{ id: 'b', title: 'Mood', updated_at: '' }], status: null }, {} as never)
    expect(root.textContent).toContain('Add this page')
    expect(root.textContent).not.toContain('Pair with your board')
  })
})

describe('pair', () => {
  it('builds the pair body', () => {
    expect(pairRequestBody(' 123456 ')).toEqual({ code: '123456' })
  })
})
