import type { ReactNode } from 'react'
import type { AgentMessage } from '../../api'
import { toolCall } from '../agentRun'
import { type Entry, textParts } from './thread'

/** Agent text with each item id as a button that focuses the item. */
function AgentText({ text, onFocusItem }: { text: string; onFocusItem: (itemId: string) => void }) {
  return (
    <>
      {textParts(text).map((p, i) =>
        'itemId' in p ? (
          <button key={i} type="button" className="chat-item-ref" onClick={() => onFocusItem(p.itemId)}>
            {p.itemId}
          </button>
        ) : (
          p.text
        ),
      )}
    </>
  )
}

/**
 * The chat with Muse's agent, oldest first: the person's and the agent's bubbles, and the agent's tool
 * calls between them as short lines. A question shows as text unless `renderQuestion` draws it.
 */
export function ChatThread({
  entries,
  onFocusItem,
  renderQuestion,
}: {
  entries: Entry[]
  onFocusItem: (itemId: string) => void
  renderQuestion?: (message: AgentMessage) => ReactNode
}) {
  return (
    <ol className="chat-thread" aria-label="Chat">
      {entries.map((e) => {
        if (e.kind === 'step') {
          const { step } = e
          const body = (
            <>
              {step.say && <span className="agent-say">{step.say}</span>}
              <code className="agent-call">{toolCall(step)}</code>
              {!step.ok && <span className="agent-refused">refused</span>}
            </>
          )
          const first = step.item_ids[0]
          return (
            <li key={`s-${step.id}`} className={step.ok ? 'chat-step' : 'chat-step refused'}>
              {first ? (
                <button type="button" className="agent-step" onClick={() => onFocusItem(first)}>
                  {body}
                </button>
              ) : (
                <div className="agent-step">{body}</div>
              )}
            </li>
          )
        }
        const { message } = e
        return (
          <li key={`m-${message.id}`} className="chat-message" data-role={message.role}>
            {message.role === 'question' && renderQuestion ? (
              renderQuestion(message)
            ) : message.role === 'person' ? (
              message.text
            ) : (
              <AgentText text={message.text} onFocusItem={onFocusItem} />
            )}
          </li>
        )
      })}
    </ol>
  )
}
