import type { Item, ItemLicence } from '../api'
import { safeExternalUrl } from '../format'
import type { Bounds } from './geometry'

const GAP = 6 // screen px between the image's bottom edge and the caption

/**
 * "© creator · licence · Source ↗" for a licensed image, from its stored provenance only (never
 * invented). With no recorded creator the stored attribution text stands in.
 */
export function CreditLine({ licence, className }: { licence: ItemLicence; className?: string }) {
  const who = licence.creator_name ? `© ${licence.creator_name}` : licence.credit
  const licenceHref = safeExternalUrl(licence.license_url)
  const sourceHref = safeExternalUrl(licence.landing_url)
  return (
    <p className={className} role="note" aria-label="Image credit" title={licence.credit}>
      {who}
      {licence.license_code && (
        <>
          {' · '}
          {licenceHref ? (
            <a href={licenceHref} target="_blank" rel="noopener noreferrer">
              {licence.license_code}
            </a>
          ) : (
            licence.license_code
          )}
        </>
      )}
      {sourceHref && (
        <>
          {' · '}
          <a href={sourceHref} target="_blank" rel="noopener noreferrer">
            Source ↗
          </a>
        </>
      )}
    </p>
  )
}

/** The credit caption under a licensed image on the canvas: outside the image, never over it. */
export function CreditCaption({ item, screen }: { item: Item; screen: Bounds }) {
  if (!item.licence) return null
  return (
    <div
      className="credit-caption"
      style={{ left: screen.x, top: screen.y + screen.height + GAP, maxWidth: Math.max(screen.width, 220) }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <CreditLine licence={item.licence} />
    </div>
  )
}
