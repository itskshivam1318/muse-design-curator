import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { insideOverlay } from './shortcutGuard'

afterEach(cleanup)

describe('insideOverlay', () => {
  it('is true inside a dialog or the right drawer, false on the board', () => {
    const { getByText } = render(
      <>
        <button type="button">board</button>
        <div role="dialog">
          <button type="button">in dialog</button>
        </div>
        <aside className="right-drawer">
          <button type="button">in drawer</button>
        </aside>
      </>,
    )
    expect(insideOverlay(getByText('in dialog'))).toBe(true)
    expect(insideOverlay(getByText('in drawer'))).toBe(true)
    expect(insideOverlay(getByText('board'))).toBe(false)
    expect(insideOverlay(null)).toBe(false)
    expect(insideOverlay(window)).toBe(false)
  })
})
