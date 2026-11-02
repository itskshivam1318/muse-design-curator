import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import '../panels/registerPanels'
import { makeItem } from '../test/fixtures'
import { ItemToolbar } from './ItemToolbar'

afterEach(cleanup)

const noop = () => {}
const screenBox = { x: 0, y: 100, width: 100, height: 100 }
const names = () => screen.getAllByRole('button').map((b) => b.textContent).concat(screen.queryAllByRole('link').map((a) => a.textContent))

describe('ItemToolbar', () => {
  it('toolbar has Inspect, Not this, Remove and no Explore', () => {
    render(<ItemToolbar items={[makeItem({ page_url: 'https://example.org' })]} screen={screenBox} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} />)
    expect(names()).toEqual(['Inspect', 'Not this', 'Remove', 'Open source ↗'])
    expect(screen.queryByRole('button', { name: /Explore|Vary/ })).toBeNull()
    expect(document.querySelector('[aria-keyshortcuts="V"]')).toBeNull()
  })

  it('2–4 items: Compare · Not this · Remove; 5 items: no Compare', () => {
    const two = [makeItem({ id: 'a' }), makeItem({ id: 'b' })]
    render(<ItemToolbar items={two} screen={screenBox} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} />)
    expect(names()).toEqual(['Compare', 'Not this', 'Remove'])
    cleanup()
    const five = ['a', 'b', 'c', 'd', 'e'].map((id) => makeItem({ id }))
    render(<ItemToolbar items={five} screen={screenBox} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} />)
    expect(names()).toEqual(['Not this', 'Remove'])
  })
})

describe('ItemToolbar source link', () => {
  it('renders Open source only for http(s) URLs', () => {
    const props = { screen: screenBox, onInspect: noop, onCompare: noop, onNotThis: noop, onRemove: noop }
    render(<ItemToolbar items={[makeItem({ page_url: 'javascript:alert(1)', source_url: 'data:text/html,x' })]} {...props} />)
    expect(screen.queryByRole('link')).toBeNull()
    cleanup()
    render(<ItemToolbar items={[makeItem({ page_url: 'javascript:alert(1)', source_url: 'https://cdn.example.org/a.jpg' })]} {...props} />)
    expect(screen.getByRole('link', { name: /Open source/ }).getAttribute('href')).toBe('https://cdn.example.org/a.jpg')
  })
})

describe('ItemToolbar Re-analyse', () => {
  const props = { screen: screenBox, onInspect: noop, onCompare: noop, onNotThis: noop, onRemove: noop }
  const button = () => screen.queryByRole('button', { name: 'Re-analyse' }) as HTMLButtonElement | null

  it('is on one image or video on the board, whatever its status (failed, legacy, waiting for a lens)', () => {
    const onReanalyse = vi.fn(() => Promise.resolve())
    for (const over of [
      { kind: 'image' as const, parse_status: 'failed' as const, parse_error_code: 'DAILY_LIMIT' },
      { kind: 'video' as const, parse_status: 'pending_lens' as const },
    ]) {
      render(<ItemToolbar items={[makeItem({ id: 'i1', ...over })]} {...props} onReanalyse={onReanalyse} />)
      expect(button()?.disabled).toBe(false)
      fireEvent.click(button()!)
      expect(onReanalyse).toHaveBeenLastCalledWith('i1')
      cleanup()
    }
    expect(onReanalyse).toHaveBeenCalledTimes(2)
  })

  it('is not on links, staged takes or a multi-selection; disabled while analysing or locked', () => {
    const onReanalyse = vi.fn(() => Promise.resolve())
    for (const items of [[makeItem({ kind: 'link' })], [makeItem({ staged: true })], [makeItem({ id: 'a' }), makeItem({ id: 'b' })]]) {
      render(<ItemToolbar items={items} {...props} onReanalyse={onReanalyse} />)
      expect(button()).toBeNull()
      cleanup()
    }
    render(<ItemToolbar items={[makeItem({ parse_status: 'pending' })]} {...props} onReanalyse={onReanalyse} />)
    expect(button()?.disabled).toBe(true)
    cleanup()
    render(<ItemToolbar items={[makeItem()]} {...props} onReanalyse={onReanalyse} readOnly />)
    expect(button()?.disabled).toBe(true)
  })

  it('shows the daily limit inline when the board is out of analyses', async () => {
    const message = 'Daily limit reached for this board, try tomorrow.'
    const onReanalyse = vi.fn(() => Promise.reject(new ApiError(429, 'DAILY_LIMIT', message)))
    render(<ItemToolbar items={[makeItem({ id: 'i1' })]} {...props} onReanalyse={onReanalyse} />)
    fireEvent.click(button()!)
    expect((await screen.findByRole('alert')).textContent).toBe(message)
  })
})
