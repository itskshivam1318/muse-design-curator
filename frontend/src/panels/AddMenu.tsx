import { type RefObject, useEffect, useId, useRef, useState } from 'react'
import { ApiError, pairCode } from '../api'
import { asHttpUrl } from '../canvas/paste'
import { formatPairCode } from '../format'
import { ACCEPT } from '../validation'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onFiles: (files: File[]) => void
  onLink: (url: string) => Promise<unknown>
}

type Pane = 'menu' | 'link' | 'extension'

/** The + button: upload, paste a link, or pair the Chrome extension. */
export function AddMenu({ open, onOpenChange, onFiles, onLink }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  return (
    <div className="add-menu" ref={rootRef}>
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
          onOpenChange(false)
        }}
      />
      {open && (
        <AddPanel rootRef={rootRef} onClose={() => onOpenChange(false)} onUpload={() => fileRef.current?.click()} onLink={onLink} />
      )}
      <button
        type="button"
        className="add-btn"
        aria-label="Add to board"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => onOpenChange(!open)}
      >
        <span aria-hidden="true">+</span>
      </button>
    </div>
  )
}

interface PanelProps {
  rootRef: RefObject<HTMLDivElement | null>
  onClose: () => void
  onUpload: () => void
  onLink: (url: string) => Promise<unknown>
}

/** Mounted only while the menu is open, so every opening starts fresh. */
function AddPanel({ rootRef, onClose, onUpload, onLink }: PanelProps) {
  const [pane, setPane] = useState<Pane>('menu')
  const [url, setUrl] = useState('')
  const [linkError, setLinkError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [code, setCode] = useState<string | null>(null)
  const [codeError, setCodeError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const ids = useId()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown)
    }
  }, [onClose, rootRef])

  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>('input, button')?.focus()
  }, [pane])

  const showExtension = async () => {
    setPane('extension')
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
      onClose()
    } catch (e) {
      setLinkError(e instanceof Error ? e.message : 'Could not add that link')
      setBusy(false)
    }
  }

  return (
    <div ref={panelRef} className="add-panel" role="dialog" aria-label="Add to board">
      {pane === 'menu' && (
        <ul className="menu-list">
          <li>
            <button type="button" onClick={onUpload}>
              <b>Upload images or video</b>
              <span>JPEG, PNG, WebP, GIF up to 10 MiB · MP4, MOV, WebM up to 100 MiB</span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => setPane('link')}>
              <b>Paste a link</b>
              <span>Or press ⌘V anywhere on the board</span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => void showExtension()}>
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
            <button type="button" className="btn-quiet" onClick={() => setPane('menu')}>
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
            <button type="button" className="btn-quiet" onClick={() => setPane('menu')}>
              Back
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
