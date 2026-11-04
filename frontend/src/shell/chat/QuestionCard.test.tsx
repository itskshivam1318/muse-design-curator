import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeMessage } from '../../test/fixtures'
import { partConfirmStore } from '../partConfirm'
import { QuestionCard } from './QuestionCard'
import { answerLine } from './thread'

afterEach(() => {
  cleanup()
  partConfirmStore.set(null)
})

const ask = (choices?: string[], answered = false) =>
  makeMessage({
    id: 'q1',
    role: 'question',
    text: 'Which palette?',
    answered,
    data: { call_id: 'c1', tool: 'ask_user', args: { question: 'Which palette?', choices } },
  })

const confirm = (answered = false) =>
  makeMessage({
    id: 'q2',
    role: 'question',
    text: 'Is this the lamp shade?',
    answered,
    data: {
      call_id: 'c2',
      tool: 'confirm_part',
      args: { item_id: 'itm_7', part: 'shade', why: 'to recolour it' },
      region: { kind: 'mask', box: [0.2, 0.1, 0.5, 0.4], mask_url: '/api/media/masks/shade.png' },
    },
  })

describe('QuestionCard', () => {
  it('ask_user choices render as buttons and answer with choice', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard message={ask(['Warm', 'Cool'])} onAnswer={onAnswer} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cool' }))
    expect(onAnswer).toHaveBeenCalledWith({ call_id: 'c1', choice: 'Cool' })
  })

  it('item-id choices render thumbnails', () => {
    render(<QuestionCard message={ask(['itm_a1', 'itm_b2'])} onAnswer={vi.fn()} />)
    const btn = screen.getByRole('button', { name: 'itm_b2' })
    expect(btn.querySelector('img')?.getAttribute('src')).toContain('/api/items/itm_b2/image')
  })

  it('the text field answers with text', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard message={ask(['Warm'])} onAnswer={onAnswer} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Answer' }), { target: { value: 'Something earthy' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }))
    expect(onAnswer).toHaveBeenCalledWith({ call_id: 'c1', text: 'Something earthy' })
  })

  it('item ids in the question are clickable', () => {
    const onFocusItem = vi.fn()
    render(<QuestionCard message={{ ...ask(), text: 'Keep itm_3?' }} onAnswer={vi.fn()} onFocusItem={onFocusItem} />)
    fireEvent.click(screen.getByRole('button', { name: 'itm_3' }))
    expect(onFocusItem).toHaveBeenCalledWith('itm_3')
  })

  it('confirm_part Yes answers yes', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard message={confirm()} onAnswer={onAnswer} />)
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    expect(onAnswer).toHaveBeenCalledWith({ call_id: 'c2', text: 'yes' })
  })

  it('confirm_part shows its part on the board; Fix enters box mode', () => {
    render(<QuestionCard message={confirm()} onAnswer={vi.fn()} />)
    expect(partConfirmStore.get()).toMatchObject({
      callId: 'c2',
      itemId: 'itm_7',
      maskUrl: '/api/media/masks/shade.png',
      box: [0.2, 0.1, 0.5, 0.4],
      mode: 'show',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Fix' }))
    expect(partConfirmStore.get()?.mode).toBe('draw')
    expect(screen.getByText(/Drag a box/)).toBeTruthy()
  })

  it('a box drawn on the board answers through onAnswer', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard message={confirm()} onAnswer={onAnswer} />)
    act(() => partConfirmStore.get()!.answer({ call_id: 'c2', box: [0.1, 0.1, 0.6, 0.6] }))
    expect(onAnswer).toHaveBeenCalledWith({ call_id: 'c2', box: [0.1, 0.1, 0.6, 0.6] })
  })

  it('leaving the thread ends the confirmation', () => {
    const { unmount } = render(<QuestionCard message={confirm()} onAnswer={vi.fn()} />)
    unmount()
    expect(partConfirmStore.get()).toBeNull()
  })

  it('answered questions render without buttons', () => {
    render(<QuestionCard message={ask(['Warm', 'Cool'], true)} onAnswer={vi.fn()} />)
    expect(screen.getByText('Which palette?')).toBeTruthy()
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.queryByRole('textbox')).toBeNull()
    cleanup()
    render(<QuestionCard message={confirm(true)} onAnswer={vi.fn()} />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(partConfirmStore.get()).toBeNull()
  })
})

describe('answerLine', () => {
  it('says the answer as a short human line', () => {
    expect(answerLine({ call_id: 'c', choice: 'Warm' })).toBe('Warm')
    expect(answerLine({ call_id: 'c', text: 'yes' })).toBe('Yes')
    expect(answerLine({ call_id: 'c', box: [0, 0, 1, 1] })).toBe('Fixed with a box')
    expect(answerLine({ call_id: 'c', text: 'the left one' })).toBe('the left one')
  })
})
