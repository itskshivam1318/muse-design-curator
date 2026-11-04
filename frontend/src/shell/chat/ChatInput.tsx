import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { type AgentMessage, type AgentRun, sendAgentMessage } from '../../api'

/**
 * The agent card's input: Enter sends the text with the selected pictures. Disabled, it shows why
 * (`disabledReason`) in place of the placeholder. A refused send shows under the input and keeps the text.
 */
export function ChatInput({
  boardId,
  disabledReason,
  selection,
  onSend,
}: {
  boardId: string
  disabledReason: string | null
  /** The selected item ids, sent as what the message is about. */
  selection: readonly string[]
  onSend: (sent: { run: AgentRun; message: AgentMessage }) => void
}) {
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: (body: { text: string; selection: string[] }) => sendAgentMessage(boardId, body),
    onSuccess: (sent) => {
      setText('')
      onSend(sent)
    },
  })
  const disabled = disabledReason !== null
  const trimmed = text.trim()
  const canSend = !disabled && trimmed !== '' && !send.isPending
  const submit = () => {
    if (canSend) send.mutate({ text: trimmed, selection: [...selection] })
  }
  const inputId = `agent-input-${boardId}`
  const n = selection.length
  return (
    <div className="chat-input">
      {n > 0 && !disabled && (
        <span className="chat-chip">
          About: {n} {n === 1 ? 'picture' : 'pictures'} selected
        </span>
      )}
      <div className="agent-ask">
        <label htmlFor={inputId} className="sr-only">
          Message Muse
        </label>
        <input
          id={inputId}
          type="text"
          placeholder={disabledReason ?? 'Ask Muse about this board'}
          disabled={disabled}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button type="button" className="agent-send" aria-label="Send" disabled={!canSend} onClick={submit}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M7 11.5v-9M3 6.5l4-4 4 4" />
          </svg>
        </button>
      </div>
      {send.isError && <p className="agent-error chat-send-error">{send.error.message}</p>}
    </div>
  )
}
