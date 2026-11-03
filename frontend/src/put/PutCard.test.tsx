import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type PartView } from '../api'
import { makeItem } from '../test/fixtures'
import { PutCard } from './PutCard'
import type { Spot } from './spots'

afterEach(cleanup)

const part = (key: string, label: string): PartView => ({ key, label, region_kind: 'box', region: [0, 0, 1, 1], mask_url: null, source: 'ai' })
const wheels: Spot[] = [
  { kind: 'part', part: part('front_wheel', 'Front wheel') },
  { kind: 'part', part: part('rear_wheel', 'Rear wheel') },
]
const source = makeItem({ id: 'src', original_filename: 'bike.jpg' })
const target = makeItem({ id: 'tgt', original_filename: null, page_title: null, creator_handle: null })

function setup(onSubmit: (words: string) => Promise<void> = () => Promise.resolve(), spots: Spot[] = wheels) {
  const onCancel = vi.fn()
  const submit = vi.fn(onSubmit)
  function Harness() {
    const [off, setOff] = useState<Set<number>>(new Set())
    const toggle = (i: number) =>
      setOff((cur) => {
        const next = new Set(cur)
        if (next.has(i)) next.delete(i)
        else next.add(i)
        return next
      })
    return <PutCard source={source} target={target} spots={spots} off={off} onToggle={toggle} onCancel={onCancel} onSubmit={submit} />
  }
  render(<Harness />)
  return { onCancel, submit }
}

const chip = (name: string) => screen.getByRole('button', { name })
const putIn = () => screen.getByRole('button', { name: 'Put in' })

describe('PutCard', () => {
  it('titles the card source → target, falling back to Picture', () => {
    setup()
    expect(screen.getByText('bike.jpg → Picture')).toBeTruthy()
  })

  it('one chip per spot; switching one off strikes it, and the other then cannot be switched off', () => {
    setup()
    const front = chip('✓ Front wheel')
    const rear = chip('✓ Rear wheel')
    expect(front.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(front)
    expect(chip('✓ Front wheel').getAttribute('aria-pressed')).toBe('false')
    expect(chip('✓ Front wheel').classList.contains('is-off')).toBe(true)
    expect((rear as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(rear)
    expect(chip('✓ Rear wheel').getAttribute('aria-pressed')).toBe('true')
    // and back on
    fireEvent.click(chip('✓ Front wheel'))
    expect(chip('✓ Front wheel').getAttribute('aria-pressed')).toBe('true')
    expect((chip('✓ Rear wheel') as HTMLButtonElement).disabled).toBe(false)
  })

  it('a point spot reads "✓ Here"', () => {
    setup(undefined, [{ kind: 'point', fx: 0.5, fy: 0.5 }])
    expect(chip('✓ Here')).toBeTruthy()
  })

  it('the words box has the placeholder and a 200 character limit', () => {
    setup()
    const input = screen.getByPlaceholderText('Anything to add? (optional)') as HTMLInputElement
    expect(input.maxLength).toBe(200)
  })

  it('Put in sends the typed words once, even when clicked twice quickly, and is disabled meanwhile', async () => {
    let resolve!: () => void
    const { submit } = setup(() => new Promise<void>((r) => (resolve = r)))
    fireEvent.change(screen.getByPlaceholderText('Anything to add? (optional)'), { target: { value: 'keep the blur' } })
    fireEvent.click(putIn())
    fireEvent.click(putIn())
    expect(submit).toHaveBeenCalledTimes(1)
    expect(submit).toHaveBeenCalledWith('keep the blur')
    expect((putIn() as HTMLButtonElement).disabled).toBe(true)
    await act(async () => resolve())
  })

  it('Enter in the words box submits', () => {
    const { submit } = setup()
    const input = screen.getByPlaceholderText('Anything to add? (optional)')
    fireEvent.change(input, { target: { value: 'soft' } })
    fireEvent.submit(input.closest('form')!)
    expect(submit).toHaveBeenCalledWith('soft')
  })

  it('a rejected submit shows its message and the card stays', async () => {
    const { onCancel } = setup(() => Promise.reject(new ApiError(429, 'RATE_LIMITED', 'Daily limit reached')))
    await act(async () => {
      fireEvent.click(putIn())
    })
    expect(screen.getByRole('alert').textContent).toBe('Daily limit reached')
    expect(putIn()).toBeTruthy()
    expect((putIn() as HTMLButtonElement).disabled).toBe(false)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('Cancel and Esc call onCancel', () => {
    const { onCancel, submit } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(screen.getByPlaceholderText('Anything to add? (optional)'), { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledTimes(2)
    expect(submit).not.toHaveBeenCalled()
  })
})
