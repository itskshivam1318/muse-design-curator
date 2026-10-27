import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeItem } from '../test/fixtures'
import { CreditCaption } from './CreditCaption'
import { creditTargets } from './credit'

afterEach(cleanup)

const licence = {
  credit: 'Photo by Ana B, CC BY-SA 4.0, via Wikimedia Commons',
  license_code: 'CC-BY-SA-4.0',
  license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
  creator_name: 'Ana B',
  landing_url: 'https://commons.wikimedia.org/wiki/File:Watch.jpg',
  source: 'wikimedia',
}
const box = { x: 40, y: 50, width: 200, height: 150 }

describe('CreditCaption', () => {
  it('shows © creator · licence · Source ↗ from the stored provenance, below the image', () => {
    render(<CreditCaption item={makeItem({ rights_status: 'licensed', licence })} screen={box} />)
    const cap = screen.getByRole('note', { name: 'Image credit' })
    expect(cap.textContent).toBe('© Ana B · CC-BY-SA-4.0 · Source ↗')
    expect(cap.getAttribute('title')).toBe(licence.credit)
    const wrap = cap.parentElement!
    expect(wrap.style.top).toBe('206px') // outside the image: its bottom edge plus a gap
    expect(wrap.style.left).toBe('40px')
    expect(screen.getByRole('link', { name: 'Source ↗' }).getAttribute('href')).toBe(licence.landing_url)
    expect(screen.getByRole('link', { name: 'CC-BY-SA-4.0' }).getAttribute('href')).toBe(licence.license_url)
  })

  it('falls back to the attribution text when the creator is unknown, and never links unsafe URLs', () => {
    const anon = { ...licence, creator_name: null, landing_url: 'javascript:alert(1)', license_url: null }
    render(<CreditCaption item={makeItem({ rights_status: 'licensed', licence: anon })} screen={box} />)
    const cap = screen.getByRole('note', { name: 'Image credit' })
    expect(cap.textContent).toBe(`${licence.credit} · CC-BY-SA-4.0`)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('renders nothing for an item without a licence', () => {
    const { container } = render(<CreditCaption item={makeItem()} screen={box} />)
    expect(container.innerHTML).toBe('')
  })
})

describe('generated caption', () => {
  it('caption for generated item shows model, no licence', () => {
    const item = makeItem({
      licence,
      generation: { model: 'gpt-image-1', prompt: 'p', option_id: 'o1' },
    })
    render(
      <CreditCaption item={item} screen={box} verdict={{ text: 'Checking…', tone: 'pending' }} />,
    )
    expect(screen.getByText('generated · gpt-image-1')).toBeTruthy()
    expect(screen.getByText('Checking…')).toBeTruthy()
    expect(screen.queryByRole('note', { name: 'Image credit' })).toBeNull()
    expect(screen.queryByText(/Ana B/)).toBeNull()
  })

  it('generated items are caption targets', () => {
    const g = makeItem({ id: 'g', generation: { model: 'm', prompt: 'p', option_id: 'o' } })
    expect(creditTargets(g, []).map((i) => i.id)).toEqual(['g'])
  })
})

describe('creditTargets', () => {
  it('captions the hovered and the selected licensed images, once each, never links or user items', () => {
    const a = makeItem({ id: 'a', rights_status: 'licensed', licence })
    const b = makeItem({ id: 'b', rights_status: 'licensed', licence })
    const user = makeItem({ id: 'u' })
    const link = makeItem({ id: 'l', kind: 'link', rights_status: 'licensed', licence })
    expect(creditTargets(a, [a, b, user, link]).map((i) => i.id)).toEqual(['a', 'b'])
    expect(creditTargets(user, [])).toEqual([])
    expect(creditTargets(undefined, [b]).map((i) => i.id)).toEqual(['b'])
  })
})
