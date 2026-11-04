import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  type AgentAnswer,
  type AgentMessage,
  type AgentRun,
  type AgentRunWithSteps,
  type AgentStep,
  agentTraceUrl,
  getAgentMessages,
  getAgentRun,
  getAgentRuns,
  getChatStatus,
  keys,
  newChat,
  patchAgentRun,
  patchAgentStep,
  sendAgentMessage,
} from '../api'
import { useSelection } from '../canvas/selection'
import { useDemo } from '../demo'
import { applyEvent } from '../events'
import { useActivity } from './activity'
import { startSpotlight, replaySteps, useSpotlight } from './spotlight'
import { agentName, deliverableStatus, mergeFetched, mergeSteps, STATUS_TEXT, toolCall } from './agentRun'
import { ChatInput } from './chat/ChatInput'
import { ChatThread } from './chat/ChatThread'
import { QuestionCard } from './chat/QuestionCard'
import { answerLine, type Entry, threadEntries } from './chat/thread'

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

/** The board's agent runs (newest first), the shown one (the person's pick, else the latest) and its steps. */
function useRun(boardId: string, chosenId: string | null) {
  const qc = useQueryClient()
  const runs = useQuery({ queryKey: keys.agentRuns(boardId), queryFn: () => getAgentRuns(boardId) })
  const all = runs.data ?? []
  const run = all.find((r) => r.id === chosenId) ?? all[0]
  const detail = useQuery({
    queryKey: keys.agentRun(run?.id ?? ''),
    // steps that arrived as events during the fetch are kept, not overwritten by an older snapshot
    queryFn: async () => {
      const fresh = await getAgentRun(run!.id)
      return mergeFetched(fresh, qc.getQueryData<AgentRunWithSteps>(keys.agentRun(fresh.id)))
    },
    enabled: run !== undefined,
  })
  return { runs: all, run, steps: detail.data?.steps ?? [], loaded: runs.isSuccess && (run === undefined || detail.isSuccess) }
}

const isOpen = (run: AgentRun) => run.status === 'running' || run.status === 'needs_input'

/** Why the person cannot chat right now, or null when they can. */
function chatOffReason(demoMode: boolean, runs: AgentRun[], available: boolean): string | null {
  if (demoMode) return 'Chat is off in the demo. Use “Show me how” to watch a run.'
  if (runs.some((r) => r.source === 'mcp' && isOpen(r))) return 'Claude Code is working'
  if (!available) return 'Chat needs Muse Spark (REASONING_PROVIDER=muse-spark)'
  return null
}

/** The latest line of the thread, as plain text. */
const entryText = (e: Entry) => (e.kind === 'message' ? e.message.text : (e.step.say ?? e.step.tool))

/**
 * Floating bottom-right: who is working ("Muse", or "Claude Code" during an agent run), the latest
 * thing that happened (the run's latest step or chat line, else the board's activity), and the chat
 * input (disabled, saying why, in the demo, while Claude Code works or without a chat model). A Muse
 * run shows its chat thread; a Claude Code run its steps. Gives way to the right drawer.
 */
export function AgentCard({ boardId, onFocusItem }: { boardId: string; onFocusItem: (itemId: string) => void }) {
  const entries = useActivity()
  const { drawer, selected } = useSelection()
  const { demoMode, locked } = useDemo()
  // a link /boards/<id>?replay=<run> opens that run's replay, once
  const [linked] = useState(() => new URLSearchParams(window.location.search).get('replay'))
  const [pick, setPick] = useState<string | null>(linked)
  const { runs, run, steps, loaded } = useRun(boardId, pick)
  const spotlight = useSpotlight()
  const qc = useQueryClient()
  const chat = run?.source === 'muse'
  const messages = useQuery({
    queryKey: keys.agentMessages(run?.id ?? ''),
    queryFn: () => getAgentMessages(run!.id),
    enabled: chat,
  })
  const chatStatus = useQuery({ queryKey: keys.chatStatus(), queryFn: getChatStatus, staleTime: 60_000, retry: false })
  const star = useMutation({
    mutationFn: (step: AgentStep) => patchAgentStep(step.id, { highlight: !step.highlight }),
    onSuccess: (step) =>
      qc.setQueryData<AgentRunWithSteps>(keys.agentRun(step.run_id), (old) =>
        old ? { ...old, steps: mergeSteps(old.steps, step) } : old,
      ),
  })
  // the person ends an open run; the answer goes in the cache the way the board's agent.run event would
  const stop = useMutation({
    mutationFn: (runId: string) => patchAgentRun(runId, { status: 'paused' }),
    onSuccess: (paused) => applyEvent(qc, boardId, 'agent.run', paused),
  })
  // the run's chat ends; the next message starts a fresh run
  const fresh = useMutation({
    mutationFn: (runId: string) => newChat(runId),
    onSuccess: (ended) => applyEvent(qc, boardId, 'agent.run', ended),
  })
  // a sent message shows its run's thread, the way its events would
  const onSent = (sent: { run: AgentRun; message: AgentMessage }) => {
    applyEvent(qc, boardId, 'agent.run', sent.run)
    applyEvent(qc, boardId, 'agent.message', sent.message)
    setPick(sent.run.id)
    setExpanded(true)
  }
  // an answer to the agent's question; its line is what the person's bubble says. The server closes
  // the question at once and says so (agent.question, answered), which takes its buttons away
  const answer = useMutation({
    mutationFn: (a: AgentAnswer) => sendAgentMessage(boardId, { text: answerLine(a), selection: [...selected], answer: a }),
    onSuccess: onSent,
  })
  const linkHandled = useRef(linked === null)
  useEffect(() => {
    if (linkHandled.current || !loaded) return
    linkHandled.current = true
    if (run?.id === linked && run.status === 'done' && replaySteps(steps).length > 0) startSpotlight(boardId, run.id, steps)
    const url = new URL(window.location.href)
    url.searchParams.delete('replay')
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
  }, [loaded, run, steps, linked, boardId])
  const [wantExpanded, setExpanded] = useState(false)
  // a replay collapses the card: expanded it would cover the board
  const expanded = wantExpanded && !spotlight
  if (drawer) return null
  const latest = entries.at(-1)
  const lastStep = steps.at(-1)
  const thread = chat ? threadEntries(messages.data ?? [], steps) : []
  const lastEntry = thread.at(-1)
  const open = run !== undefined && isOpen(run)
  // an open chat that is not mid-turn: waiting for the person, or for an answer
  const canNewChat = chat && (run.status === 'waiting' || run.status === 'needs_input') && !locked
  const offReason = chatOffReason(demoMode, runs, chatStatus.data?.available === true)
  const canReplay = run?.status === 'done' && replaySteps(steps).length > 0
  const showMeHow = run && canReplay && (
    <button type="button" className="agent-replay" disabled={spotlight !== null} onClick={() => startSpotlight(boardId, run.id, steps)}>
      {spotlight ? 'Replaying…' : 'Show me how'}
    </button>
  )
  return (
    <aside className="agent-card" aria-label="Muse agent">
      <div className="agent-head">
        {run ? (
          <span className="agent-who">
            <span className="agent-name">{agentName(run)}</span>
            <span className="agent-status" data-status={run.status}>
              {STATUS_TEXT[run.status]}
            </span>
            {open && !locked && (
              <button type="button" className="agent-stop" disabled={stop.isPending} onClick={() => stop.mutate(run.id)}>
                Stop run
              </button>
            )}
            {canNewChat && (
              <button type="button" className="agent-stop" disabled={fresh.isPending} onClick={() => fresh.mutate(run.id)}>
                New chat
              </button>
            )}
          </span>
        ) : (
          <span className="agent-name">Muse</span>
        )}
        <button
          type="button"
          className="icon-btn"
          aria-label="Show activity"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
            {expanded ? <path d="M3 5l4 4 4-4" /> : <path d="M8.5 2.5h3v3M5.5 11.5h-3v-3M11.5 2.5L8 6M2.5 11.5L6 8" />}
          </svg>
        </button>
      </div>
      {stop.isError && (
        <p className="agent-error agent-stop-error" role="alert">
          Could not stop the run.
        </p>
      )}
      {fresh.isError && (
        <p className="agent-error agent-stop-error" role="alert">
          Could not start a new chat.
        </p>
      )}
      {run ? (
        expanded ? (
          <div className="agent-run">
            {runs.length > 1 && (
              <select aria-label="Run" className="agent-run-pick" value={run.id} onChange={(e) => setPick(e.target.value)}>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {agentName(r)} · {clock(r.created_at)} · {r.goal.slice(0, 40)}
                  </option>
                ))}
              </select>
            )}
            {chat ? (
              <a className="agent-trace" href={agentTraceUrl(run.id)} download>
                Download trace
              </a>
            ) : (
              <p className="agent-goal">{run.goal}</p>
            )}
            {run.deliverables.length > 0 && (
              <ul className="agent-deliverables" aria-label="Deliverables">
                {deliverableStatus(run).map((d) => (
                  <li key={d.name}>
                    <label>
                      <input type="checkbox" checked={d.done} readOnly disabled /> {d.name}
                    </label>
                  </li>
                ))}
              </ul>
            )}
            {showMeHow}
            {chat ? (
              thread.length > 0 && (
                <ChatThread
                  entries={thread}
                  onFocusItem={onFocusItem}
                  renderQuestion={(m) => (
                    <QuestionCard
                      message={m}
                      onAnswer={(a) => answer.mutate(a)}
                      onFocusItem={onFocusItem}
                      disabled={answer.isPending || offReason !== null}
                    />
                  )}
                />
              )
            ) : steps.length > 0 && (
              <ol className="agent-log agent-steps" aria-label="Steps">
                {[...steps].reverse().map((step) => {
                  const body = (
                    <>
                      {step.say && <span className="agent-say">{step.say}</span>}
                      <code className="agent-call">{toolCall(step)}</code>
                      {!step.ok && <span className="agent-refused">refused</span>}
                    </>
                  )
                  const first = step.item_ids[0]
                  return (
                    <li key={step.id} className={step.ok ? undefined : 'refused'}>
                      {first ? (
                        <button type="button" className="agent-step" onClick={() => onFocusItem(first)}>
                          {body}
                        </button>
                      ) : (
                        <div className="agent-step">{body}</div>
                      )}
                      {!locked && (
                        <button
                          type="button"
                          className="icon-btn agent-star"
                          aria-label="Highlight step"
                          aria-pressed={step.highlight}
                          onClick={() => star.mutate(step)}
                        >
                          <svg width="14" height="14" viewBox="0 0 14 14" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" fill={step.highlight ? 'currentColor' : 'none'} aria-hidden="true">
                            <path d="M7 1.8l1.6 3.3 3.6.5-2.6 2.5.6 3.6L7 10l-3.2 1.7.6-3.6-2.6-2.5 3.6-.5z" />
                          </svg>
                        </button>
                      )}
                    </li>
                  )
                })}
              </ol>
            )}
            {answer.isError && (
              <p className="agent-error" role="alert">
                Could not send your answer.
              </p>
            )}
            {star.isError && (
              <p className="agent-error" role="alert">
                Could not highlight that step.
              </p>
            )}
          </div>
        ) : (
          <>
            <p className="agent-latest" aria-live="polite">
              {chat ? (lastEntry ? entryText(lastEntry) : run.goal) : lastStep ? (lastStep.say ?? lastStep.tool) : run.goal}
            </p>
            {showMeHow}
          </>
        )
      ) : expanded ? (
        entries.length > 0 ? (
          <ol className="agent-log" aria-label="Activity">
            {[...entries].reverse().map((e, i) => (
              <li key={`${e.at}-${i}`}>
                <span>{e.text}</span> <time dateTime={e.at}>{clock(e.at)}</time>
              </li>
            ))}
          </ol>
        ) : (
          <p className="agent-latest">Nothing yet.</p>
        )
      ) : (
        <p className="agent-latest" aria-live="polite">
          {latest?.text ?? 'Nothing yet.'}
        </p>
      )}
      <ChatInput
        boardId={boardId}
        disabledReason={offReason}
        selection={selected}
        onSend={onSent}
      />
    </aside>
  )
}
