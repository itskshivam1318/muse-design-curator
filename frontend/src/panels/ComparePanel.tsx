import { useQueries } from '@tanstack/react-query'
import { getAttributes, itemImageUrl, keys } from '../api'
import { selection } from '../canvas/selection'
import { useItems } from '../queries'
import { compareDiff, numberBounds, valueToWire } from '../vary/logic'
import { ValueText } from './AttrBits'
import { itemTitle } from '../format'
import type { DrawerPanelProps } from './drawerRegistry'
import { PanelHead } from './PanelHead'

/** 2–4 selected items side by side: only the attributes where they differ. */
export function ComparePanel({ boardId, itemId, params, onClose }: DrawerPanelProps) {
  const ids = (Array.isArray(params?.itemIds) ? (params.itemIds as string[]) : [itemId]).slice(0, 4)
  const items = useItems(boardId).data ?? []
  const results = useQueries({
    queries: ids.map((id) => ({ queryKey: keys.attributes(id), queryFn: () => getAttributes(id) })),
  })
  const loading = results.some((r) => r.isPending)
  const failed = results.find((r) => r.isError)
  const lens = results.find((r) => r.data?.lens)?.data?.lens
  const rows = loading ? [] : compareDiff(ids.map((id, i) => ({ itemId: id, attributes: results[i].data?.attributes ?? [] })))
  const first = ids[0]

  return (
    <div className="panel compare-panel">
      <PanelHead eyebrow="Compare" title={`${ids.length} items`} onClose={onClose} />
      <div className="panel-body">
        {loading && <p className="muted">Loading attributes…</p>}
        {failed && <p className="error">Could not load attributes: {failed.error?.message}</p>}
        {!loading && rows.length === 0 && !failed && <p className="muted">These items agree on every known attribute.</p>}
        {rows.length > 0 && (
          <table className="compare">
            <thead>
              <tr>
                <td />
                {ids.map((id) => {
                  const it = items.find((i) => i.id === id)
                  return (
                    <th key={id} scope="col">
                      {it && it.kind !== 'link' ? <img src={itemImageUrl(it, 'thumb')} alt={itemTitle(it)} /> : (it ? itemTitle(it) : id)}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const unit = numberBounds(lens?.attributes.find((a) => a.key === r.key))?.unit
                return (
                  <tr key={r.key}>
                    <th scope="row">{r.label}</th>
                    {r.values.map((v, i) => (
                      <td key={ids[i]}>
                        <ValueText kind={r.kind} value={v} unit={unit} />
                        {i > 0 && v !== null && v !== r.values[0] && (
                          <button
                            type="button"
                            className="link-btn small"
                            aria-label={`Vary toward this: ${r.label}`}
                            onClick={() =>
                              selection.openDrawer('vary', first, {
                                targetKey: r.key,
                                mode: 'prefer',
                                values: [valueToWire(v)],
                              })
                            }
                          >
                            Vary toward this
                          </button>
                        )}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
