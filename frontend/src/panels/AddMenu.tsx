import { useEffect, useId, useRef, useState } from 'react'
import { ApiError, pairCode } from '../api'
import { asHttpUrl } from '../canvas/paste'
import { formatPairCode } from '../format'
import { LOCKED_TITLE } from '../demo'
import { ACCEPT } from '../validation'

interface Props {
  onFiles: (files: File[]) => void
  onLink: (url: string) => Promise<unknown>
  /** Public demo, not unlocked: nothing can be added. */
  disabled?: boolean
}

type Pane = 'menu' | 'link' | 'extension'

/** Add to the board: upload, paste a link, or pair the Chrome extension (rendered in the Library panel). */
export function AddActions({ onFiles, onLink, disabled = false }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [pane, setPane] = useState<Pane>('menu')
  const [url, setUrl] = useState('')
  const [linkError, setLinkError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [code, setCode] = useState<string | null>(null)
  const [codeError, setCodeError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const moved = useRef(false)
  const ids = useId()

  // focus follows the pane once the person has moved between panes (not on first render)
  useEffect(() => {
    if (!moved.current) return
    panelRef.current?.querySelector<HTMLElement>('input:not(.sr-only), button')?.focus()
  }, [pane])

  const go = (next: Pane) => {
    moved.current = true
    setPane(next)
  }

  const backToMenu = () => {
    setUrl('')
    setBusy(false)
    go('menu')
  }

  const lockTitle = disabled ? LOCKED_TITLE : undefined

  const showExtension = async () => {
    go('extension')
    setCode(null)
    setCodeError(null)
    try {
      setCode((await pairCode()).code)
    } catch (e) {
      setCodeError(e instanceof ApiError ? e.message : 'Could not get a pairing code')
    }
  }

  const submitLink = async () => {
    const u = asHttpUrl(url)
    if (!u) {
      setLinkError('Enter a full http(s) link')
      return
    }
    setBusy(true)
    setLinkError(null)
    try {
      await onLink(u)
      backToMenu()
    } catch (e) {
      setLinkError(e instanceof Error ? e.message : 'Could not add that link')
      setBusy(false)
    }
  }

  return (
    <div ref={panelRef} className="add-actions" role="group" aria-label="Add to board">
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-label="Choose images or video to upload"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
      {pane === 'menu' && (
        <ul className="menu-list">
          <li>
            <button type="button" onClick={() => fileRef.current?.click()} disabled={disabled} title={lockTitle}>
              <b>Upload images or video</b>
              <span>JPEG, PNG, WebP, GIF up to 10 MiB · MP4, MOV, WebM up to 100 MiB</span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => go('link')} disabled={disabled} title={lockTitle}>
              <b>Paste a link</b>
              <span>Or press ⌘V anywhere on the board</span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => void showExtension()} disabled={disabled} title={lockTitle}>
              <b>Get the Chrome extension</b>
              <span>Capture images and video from any page</span>
            </button>
          </li>
        </ul>
      )}
      {pane === 'link' && (
        <form
          className="pane"
          onSubmit={(e) => {
            e.preventDefault()
            void submitLink()
          }}
        >
          <label htmlFor={`${ids}-url`}>Link to a page or image</label>
          <input
            id={`${ids}-url`}
            type="url"
            inputMode="url"
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-invalid={linkError ? true : undefined}
            aria-describedby={linkError ? `${ids}-url-err` : undefined}
          />
          {linkError && (
            <p id={`${ids}-url-err`} className="error small" role="alert">
              {linkError}
            </p>
          )}
          <div className="row-end">
            <button type="button" className="btn-quiet" onClick={() => go('menu')}>
              Back
            </button>
            <button type="submit" className="btn" disabled={busy}>
              {busy ? 'Adding…' : 'Add link'}
            </button>
          </div>
        </form>
      )}
      {pane === 'extension' && (
        <div className="pane" aria-live="polite">
          {code && (
            <p>
              Install the extension, then enter this code: <b className="pair-code">{formatPairCode(code)}</b> (valid 10
              minutes)
            </p>
          )}
          {!code && !codeError && <p className="muted">Getting a pairing code…</p>}
          {codeError && (
            <p className="error small" role="alert">
              {codeError}
            </p>
          )}
          <div className="row-end">
            <button type="button" className="btn-quiet" onClick={() => go('menu')}>
              Back
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
