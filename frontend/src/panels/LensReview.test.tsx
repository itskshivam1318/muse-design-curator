import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LensRow } from '../api'
import { LensReview } from './LensReview'

afterEach(cleanup)

const lens: LensRow = {
  id: 'lens_1', board_id: 'b', domain: 'custom', version: 1, origin: 'proposed', status: 'proposed',
  created_at: '',
  spec: {
    id: 'custom@1', domain: 'custom', label: 'Lamps', origin: 'proposed',
    parts: [{ id: 'shade', sam_prompt: 'lamp shade', grounding: 'whole_image' }],
    attributes: [
      { key: 'shade_shape', label: 'Shade shape', category: 'form', kind: 'enum', part: 'shade', vocabulary: ['drum'] },
      { key: 'warmth', label: 'Warmth', category: 'light', kind: 'ordinal', scale: ['cool', 'neutral', 'warm'] },
    ],
    notes: ['Part shade was found in 3 of 10 sample images; using the whole image instead.'],
  },
}

describe('LensReview', () => {
  it('shows part hit-rate notes and attributes by kind; Confirm sends no body', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    render(<LensReview lens={lens} onConfirm={onConfirm} onDismiss={() => {}} />)
    expect(screen.getByText(/found in 3 of 10 sample images/)).toBeTruthy()
    expect(screen.getByText('Choices')).toBeTruthy()
    expect(screen.getByText('Scales')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(undefined))
  })

  it('Edit removes attributes and renames labels, then saves the edited spec', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    render(<LensReview lens={lens} onConfirm={onConfirm} onDismiss={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Warmth' }))
    fireEvent.change(screen.getByLabelText('Label for shade_shape'), { target: { value: 'Shade' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save lens' }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    const sent = onConfirm.mock.calls[0][0]
    expect(sent.attributes.map((a: { key: string }) => a.key)).toEqual(['shade_shape'])
    expect(sent.attributes[0].label).toBe('Shade')
    expect(sent.attributes[0].vocabulary).toEqual(['drum']) // the rest of the spec is kept
  })
})
