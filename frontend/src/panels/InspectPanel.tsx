import { useMemo } from 'react'
import { isGenerated } from '../api'
import { CreditLine } from '../canvas/CreditCaption'
import { itemTitle } from '../format'
import { itemVerdict } from '../explore/verdict'
import { formatValue } from '../attrValues'
import { useAnalysis, useExplorations, useItems } from '../queries'
import type { DrawerPanelProps } from './drawerRegistry'
import { inspectGroups } from './inspectGroups'
import { PanelHead } from './PanelHead'

const STALE_TITLE = 'old dimension, not found on this item'

/** What the analysis engine read from one item: its parts and dimensions, with values. */
export function InspectPanel({ boardId, itemId, onClose }: DrawerPanelProps) {
  const q = useAnalysis(itemId)
  const item = useItems(boardId).data?.find((i) => i.id === itemId)
  const explorations = useExplorations(boardId).data
  const labels = useMemo(() => new Map((q.data?.dimensions ?? []).map((d) => [d.key, d.label])), [q.data])
  const verdict = useMemo(() => (item ? itemVerdict(item, explorations, labels) : null), [item, explorations, labels])
  const groups = useMemo(() => (q.data ? inspectGroups(q.data) : []), [q.data])
  const status = q.data?.parse_status

  return (
    <div className="panel inspect-panel">
      <PanelHead
        eyebrow="Inspect"
        title={item ? itemTitle(item) : 'Item'}
        onClose={onClose}
        sub={item?.licence && !isGenerated(item) && <CreditLine licence={item.licence} className="credit panel-credit small muted" />}
      />
      <div className="panel-body">
        {item?.generation && isGenerated(item) && verdict && (
          <section className="attr-group generated-from">
            <h3 className="eyebrow">{verdict.optionName ? `Generated from ${verdict.optionName}` : 'Generated image'}</h3>
            <p className={`verdict verdict-${verdict.tone}`}>{verdict.text}</p>
            <p className="small muted">Model: {item.generation.model}</p>
            <p className="small muted">Prompt: {item.generation.prompt}</p>
          </section>
        )}
        {q.isPending && <p className="muted">Loading analysis…</p>}
        {q.isError && <p className="error">Could not load analysis: {q.error.message}</p>}
        {status && status !== 'completed' && (
          <p className="note small">
            {status === 'failed'
              ? `Analysis failed${item?.parse_error_code ? ` (${item.parse_error_code})` : ''}.`
              : 'Still reading this item; parts and dimensions will fill in.'}
          </p>
        )}
        {status === 'completed' && groups.length === 0 && <p className="muted">Nothing was found on this item.</p>}
        {groups.map((g) => (
          <section key={g.key || 'whole'} className="attr-group">
            <h3 className="eyebrow">{g.title}</h3>
            {g.dims.length === 0 ? (
              <p className="muted small">No dimensions read yet.</p>
            ) : (
              <dl className="attr-rows">
                {g.dims.map((d) => (
                  <div key={d.key} className={d.status === 'stale' ? 'attr-row is-stale' : 'attr-row'} title={d.status === 'stale' ? STALE_TITLE : undefined}>
                    <dt className="attr-label">{d.label}</dt>
                    <dd>
                      {formatValue(d.value)}
                      {d.source === 'user' && <span className="mark is-edited"> edited by you</span>}
                      {d.status === 'stale' && <span className="mark is-missing"> stale</span>}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
