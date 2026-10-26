import { type Ref, useId, useImperativeHandle, useRef, useState } from 'react'
import type { Board, BoardProfile } from '../api'
import { humanize } from '../format'
import { DOMAINS, inferredDomain, toSnake } from './domains'

const AUTO = ''
const OTHER = '__other'

interface Props {
  board: Board
  profile: BoardProfile | undefined
  onSave: (patch: Partial<Pick<Board, 'title' | 'context' | 'domain'>>) => Promise<unknown>
  ref?: Ref<ContextBarHandle>
}

export interface ContextBarHandle {
  /** Onboarding step 1: open the bar and focus the title. */
  focus: () => void
}

function domainState(board: Board) {
  const known = board.domain === null || DOMAINS.some((d) => d.value === board.domain)
  return {
    choice: board.domain === null ? AUTO : known ? board.domain : OTHER,
    other: known ? '' : (board.domain ?? ''),
  }
}

/** Floating top-left: board title (inline edit) and its one-line brief; expands to edit the brief and domain. */
export function ContextBar({ board, profile, onSave, ref }: Props) {
  const [titleDraft, setTitleDraft] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [context, setContext] = useState(board.context)
  const [domainChoice, setDomainChoice] = useState(AUTO)
  const [otherDomain, setOtherDomain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const titleRef = useRef<HTMLInputElement>(null)
  const ids = useId()
  const auto = inferredDomain(profile)
  const title = titleDraft ?? board.title

  const openEditor = () => {
    const d = domainState(board)
    setContext(board.context)
    setDomainChoice(d.choice)
    setOtherDomain(d.other)
    setOpen(true)
  }

  useImperativeHandle(ref, () => ({
    focus: () => {
      if (!open) openEditor()
      titleRef.current?.focus()
      titleRef.current?.select()
    },
  }))

  const save = async (patch: Parameters<Props['onSave']>[0]) => {
    setError(null)
    try {
      await onSave(patch)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
    }
  }

  const commitTitle = () => {
    const t = title.trim()
    setTitleDraft(null)
    if (t && t !== board.title) void save({ title: t })
  }

  const commitDetails = async () => {
    const domain = domainChoice === AUTO ? null : domainChoice === OTHER ? toSnake(otherDomain) || null : domainChoice
    await save({ context: context.trim(), domain })
    setOpen(false)
  }

  const domainText =
    board.domain !== null ? humanize(board.domain) : auto ? `Auto: ${humanize(auto).toLowerCase()}` : 'Auto'

  return (
    <section className={open ? 'context-bar is-open' : 'context-bar'} aria-label="Board context">
      <label className="sr-only" htmlFor={`${ids}-title`}>
        Board title
      </label>
      <input
        id={`${ids}-title`}
        ref={titleRef}
        className="context-title"
        value={title}
        onChange={(e) => setTitleDraft(e.target.value)}
        onBlur={commitTitle}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') {
            setTitleDraft(null)
            e.currentTarget.blur()
          }
        }}
      />
      {!open ? (
        <button
          type="button"
          className="context-summary"
          aria-expanded={false}
          onClick={openEditor}
        >
          <span className={board.context ? '' : 'is-placeholder'}>
            {board.context || "Say what it's for: one line, e.g. a dress watch for a 38 mm wrist"}
          </span>
          <span className="context-domain"> · {domainText}</span>
        </button>
      ) : (
        <form
          className="context-form"
          onSubmit={(e) => {
            e.preventDefault()
            void commitDetails()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false)
          }}
        >
          <label htmlFor={`${ids}-brief`}>What is this board for?</label>
          <textarea
            id={`${ids}-brief`}
            rows={3}
            value={context}
            placeholder="A dress-adjacent field watch for a 38 mm wrist. Legible and plain, but warmer."
            onChange={(e) => setContext(e.target.value)}
          />
          <label htmlFor={`${ids}-domain`}>Domain</label>
          <select id={`${ids}-domain`} value={domainChoice} onChange={(e) => setDomainChoice(e.target.value)}>
            <option value={AUTO}>Auto{auto ? ` (looks like ${humanize(auto).toLowerCase()})` : ''}</option>
            {DOMAINS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
            <option value={OTHER}>Other…</option>
          </select>
          {domainChoice === OTHER && (
            <>
              <label htmlFor={`${ids}-other`}>Other domain</label>
              <input
                id={`${ids}-other`}
                value={otherDomain}
                placeholder="e.g. ceramics"
                onChange={(e) => setOtherDomain(e.target.value)}
              />
            </>
          )}
          <div className="row-end">
            <button type="button" className="btn-quiet" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn">
              Save
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
