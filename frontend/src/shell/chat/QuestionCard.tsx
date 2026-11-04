import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { type AgentAnswer, type AgentMessage, itemIdImageUrl } from '../../api'
import { clearPartConfirm, partConfirmStore, setConfirmMode, usePartConfirm } from '../partConfirm'
import { textParts } from './thread'

const ITEM_ID = /^itm_[A-Za-z0-9]+$/

const isBox = (b: unknown): b is number[] => Array.isArray(b) && b.length === 4 && b.every((v) => typeof v === 'number')

/**
 * A question from the agent in the chat thread. `ask_user`: a button per choice (an item id shows its
 * thumbnail) and a text field. `confirm_part`: its part is shown on the board; Yes, Fix (draw a box over
 * the item there) or a text field. Answered, only the question is left.
 */
export function QuestionCard({
  message,
  onAnswer,
  onFocusItem,
  disabled = false,
}: {
  message: AgentMessage
  onAnswer: (answer: AgentAnswer) => void
  onFocusItem?: (itemId: string) => void
  disabled?: boolean
}) {
  const [text, setText] = useState('')
  const data = message.data
  const callId = data?.call_id ?? ''
  const args = data?.args ?? {}
  const open = !message.answered && callId !== ''
  const confirmItem = data?.tool === 'confirm_part' && typeof args.item_id === 'string' ? args.item_id : null
  const maskUrl = data?.region?.mask_url ?? null
  const rawBox = data?.region?.box
  const boxKey = isBox(rawBox) ? rawBox.join(',') : ''
  // the latest onAnswer and disabled, so a parent's new callback each render does not restart the confirmation
  const answerRef = useRef(onAnswer)
  const disabledRef = useRef(disabled)
  useEffect(() => {
    answerRef.current = onAnswer
    disabledRef.current = disabled
  })
  // every answer (a button, the field, a box drawn on the board) goes through here: none while disabled,
  // and any answer ends box drawing
  const give = useCallback(
    (a: AgentAnswer) => {
      if (disabledRef.current) return
      if (partConfirmStore.get()?.callId === callId) setConfirmMode('show')
      answerRef.current(a)
    },
    [callId],
  )
  useEffect(() => {
    if (!open || confirmItem === null) return
    partConfirmStore.set({
      callId,
      itemId: confirmItem,
      maskUrl,
      box: boxKey ? boxKey.split(',').map(Number) : null,
      mode: 'show',
      answer: give,
    })
    return () => clearPartConfirm(callId)
  }, [open, callId, confirmItem, maskUrl, boxKey, give])
  // while answers are off (one being sent, or chat off) the board takes no box
  useEffect(() => {
    if (disabled && partConfirmStore.get()?.callId === callId) setConfirmMode('show')
  }, [disabled, callId])
  const confirm = usePartConfirm()
  const drawing = confirm?.callId === callId && confirm.mode === 'draw'

  const question = (
    <p className="question-text">
      {textParts(message.text).map((p, i) =>
        'itemId' in p ? (
          onFocusItem ? (
            <button key={i} type="button" className="chat-item-ref" onClick={() => onFocusItem(p.itemId)}>
              {p.itemId}
            </button>
          ) : (
            p.itemId
          )
        ) : (
          p.text
        ),
      )}
    </p>
  )
  if (!open) return <div className="question-card is-answered">{question}</div>

  const choices = data?.tool === 'ask_user' && Array.isArray(args.choices) ? args.choices.filter((c): c is string => typeof c === 'string') : []
  const send = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    if (disabled) return
    give({ call_id: callId, text: t })
    setText('')
  }
  return (
    <div className="question-card">
      {question}
      {choices.length > 0 && (
        <div className="question-choices">
          {choices.map((c) =>
            ITEM_ID.test(c) ? (
              <button key={c} type="button" className="question-choice is-item" aria-label={c} disabled={disabled} onClick={() => give({ call_id: callId, choice: c })}>
                <img src={itemIdImageUrl(c)} alt="" />
              </button>
            ) : (
              <button key={c} type="button" className="question-choice" disabled={disabled} onClick={() => give({ call_id: callId, choice: c })}>
                {c}
              </button>
            ),
          )}
        </div>
      )}
      {confirmItem !== null && (
        <div className="question-choices">
          <button type="button" className="question-choice" disabled={disabled} onClick={() => give({ call_id: callId, text: 'yes' })}>
            Yes
          </button>
          <button
            type="button"
            className="question-choice"
            aria-pressed={drawing}
            disabled={disabled}
            onClick={() => setConfirmMode(drawing ? 'show' : 'draw')}
          >
            Fix
          </button>
        </div>
      )}
      {drawing && <p className="question-hint">Drag a box over the part on the board. Esc cancels.</p>}
      <form className="question-reply" onSubmit={send}>
        <input aria-label="Answer" placeholder="Or say…" value={text} disabled={disabled} onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="question-choice" aria-label="Send answer" disabled={disabled || !text.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
