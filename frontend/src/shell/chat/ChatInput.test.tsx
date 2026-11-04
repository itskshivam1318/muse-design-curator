import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api'
import { makeMessage, makeRun } from '../../test/fixtures'

vi.mock('../../api', async (orig) => ({
  ...(await orig<typeof import('../../api')>()),
  sendAgentMessage: vi.fn(),
}))
const api = await import('../../api')
const { ChatInput } = await import('./ChatInput')

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderInput(props: { selection?: string[]; disabledReason?: string | null; onSend?: () => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ChatInput
        boardId="b1"
        disabledReason={props.disabledReason ?? null}
        selection={props.selection ?? []}
        onSend={props.onSend ?? (() => undefined)}
      />
    </QueryClientProvider>,
  )
  return screen.getByLabelText('Message Muse') as HTMLInputElement
}

describe('ChatInput', () => {
  it('ChatInput sends text with selection', async () => {
    const sent = { run: makeRun({ source: 'muse' }), message: makeMessage({ role: 'person', text: 'Warmer' }) }
    vi.mocked(api.sendAgentMessage).mockResolvedValue(sent)
    const onSend = vi.fn()
    const input = renderInput({ selection: ['itm_1'], onSend })
    expect(screen.getByText('About: 1 picture selected')).toBeTruthy()
    fireEvent.change(input, { target: { value: 'Warmer' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(sent))
    expect(api.sendAgentMessage).toHaveBeenCalledWith('b1', { text: 'Warmer', selection: ['itm_1'] })
    expect(input.value).toBe('')
  })

  it('counts pictures in the chip, and has no chip without a selection', () => {
    renderInput({ selection: ['itm_1', 'itm_2'] })
    expect(screen.getByText('About: 2 pictures selected')).toBeTruthy()
    cleanup()
    renderInput()
    expect(screen.queryByText(/About:/)).toBeNull()
  })

  it('sends nothing for blank text', () => {
    const input = renderInput()
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(api.sendAgentMessage).not.toHaveBeenCalled()
  })

  it('ChatInput shows demo reason', () => {
    const reason = 'Chat is off in the demo. Use “Show me how” to watch a run.'
    const input = renderInput({ disabledReason: reason })
    expect(input.disabled).toBe(true)
    expect(input.placeholder).toBe(reason)
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows a refused send under the input and keeps the text', async () => {
    vi.mocked(api.sendAgentMessage).mockRejectedValue(new ApiError(409, 'RUN_BUSY', 'Muse is still working on the last message.'))
    const input = renderInput()
    fireEvent.change(input, { target: { value: 'Again' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Muse is still working on the last message.')).toBeTruthy()
    expect(input.value).toBe('Again')
  })
})
