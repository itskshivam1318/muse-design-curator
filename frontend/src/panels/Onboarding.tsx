export const UNLOCK_AT = 5

interface Props {
  itemCount: number
  onFocusContext: () => void
  onOpenAdd: () => void
}

/** Three steps drawn on the empty canvas itself. Gone as soon as the board has an item. */
export function Onboarding({ itemCount, onFocusContext, onOpenAdd }: Props) {
  if (itemCount > 0) return null
  return (
    <section className="onboarding" aria-label="Getting started">
      <ol>
        <li>
          <span className="onboarding-n" aria-hidden="true">1</span>
          <button type="button" className="onboarding-step" onClick={onFocusContext}>
            Name this board and say what it's for
          </button>
        </li>
        <li>
          <span className="onboarding-n" aria-hidden="true">2</span>
          <div>
            <button type="button" className="onboarding-step" onClick={onOpenAdd}>
              Add references
            </button>
            <p className="onboarding-hint">
              Drop images or video anywhere, paste a link with ⌘V, or open Library
            </p>
          </div>
        </li>
        <li>
          <span className="onboarding-n" aria-hidden="true">3</span>
          <div>
            <p className="onboarding-step is-static">Add 5 to unlock board intelligence</p>
            <ProgressDots count={itemCount} of={UNLOCK_AT} />
          </div>
        </li>
      </ol>
    </section>
  )
}

export function ProgressDots({ count, of }: { count: number; of: number }) {
  const n = Math.min(count, of)
  return (
    <span className="dots" role="img" aria-label={`${n} of ${of} references added`}>
      {Array.from({ length: of }, (_, i) => (
        <i key={i} className={i < n ? 'dot is-on' : 'dot'} />
      ))}
    </span>
  )
}
