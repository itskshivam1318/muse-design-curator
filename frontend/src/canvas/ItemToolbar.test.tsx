import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import '../panels/registerPanels'
import { makeItem } from '../test/fixtures'
import { ItemToolbar } from './ItemToolbar'

afterEach(cleanup)

const noop = () => {}
const screenBox = { x: 0, y: 100, width: 100, height: 100 }
const names = () => screen.getAllByRole('button').map((b) => b.textContent).concat(screen.queryAllByRole('link').map((a) => a.textContent))

describe('ItemToolbar', () => {
  it('one item: Explore · Inspect · Not this · Open source · Remove', () => {
    render(<ItemToolbar items={[makeItem({ page_url: 'https://example.org' })]} screen={screenBox} onExplore={noop} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} explore />)
    expect(names()).toEqual(['Explore', 'Inspect', 'Not this', 'Remove', 'Open source ↗'])
  })

  it('explore off: the primary button is Vary', () => {
    render(<ItemToolbar items={[makeItem()]} screen={screenBox} onExplore={noop} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} explore={false} />)
    expect(names()).toEqual(['Vary', 'Inspect', 'Not this', 'Remove'])
  })

  it('2–4 items: Compare · Not this · Remove; 5 items: no Compare', () => {
    const two = [makeItem({ id: 'a' }), makeItem({ id: 'b' })]
    render(<ItemToolbar items={two} screen={screenBox} onExplore={noop} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} />)
    expect(names()).toEqual(['Compare', 'Not this', 'Remove'])
    cleanup()
    const five = ['a', 'b', 'c', 'd', 'e'].map((id) => makeItem({ id }))
    render(<ItemToolbar items={five} screen={screenBox} onExplore={noop} onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} />)
    expect(names()).toEqual(['Not this', 'Remove'])
  })
})

describe('ItemToolbar source link', () => {
  it('renders Open source only for http(s) URLs', () => {
    const props = { screen: screenBox, onExplore: noop, onInspect: noop, onCompare: noop, onNotThis: noop, onRemove: noop }
    render(<ItemToolbar items={[makeItem({ page_url: 'javascript:alert(1)', source_url: 'data:text/html,x' })]} {...props} />)
    expect(screen.queryByRole('link')).toBeNull()
    cleanup()
    render(<ItemToolbar items={[makeItem({ page_url: 'javascript:alert(1)', source_url: 'https://cdn.example.org/a.jpg' })]} {...props} />)
    expect(screen.getByRole('link', { name: /Open source/ }).getAttribute('href')).toBe('https://cdn.example.org/a.jpg')
  })
})
