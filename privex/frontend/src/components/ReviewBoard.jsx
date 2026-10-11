import { useState, useRef, useEffect } from 'react'
import { applyRedactions, downloadUrl } from '../api/client'
import styles from './ReviewBoard.module.css'

const TYPE_COLOR = { face: '#ff3356', text: '#ffb300', default: '#4488ff' }
const STYLES = ['black', 'blur', 'pixelate']

export default function ReviewBoard({ data, onReset }) {
  // proposals: each has { id, type, label, reason, sensitive, approved, bbox, value?, context? }
  const [proposals, setProposals] = useState(() =>
    (data.proposals || []).map(p => ({ ...p }))
  )
  const [hoveredId,    setHoveredId]    = useState(null)
  const [applying,     setApplying]     = useState(false)
  const [result,       setResult]       = useState(null)
  const [error,        setError]        = useState(null)
  const [filterMode,   setFilterMode]   = useState('all') // all | sensitive | safe
  const [redactStyle,  setRedactStyle]  = useState('black')
  const canvasRef  = useRef()
  const imageRef   = useRef()

  const imgW = data.image_w || 800
  const imgH = data.image_h || 600
  const src  = `data:image/jpeg;base64,${data.preview_jpg_b64}`

  // Draw redaction overlays on canvas whenever proposals or hover changes
  useEffect(() => {
    const canvas = canvasRef.current
    const img    = imageRef.current
    if (!canvas || !img || !img.complete) return

    const cw = canvas.width
    const ch = canvas.height
    const scaleX = cw / imgW
    const scaleY = ch / imgH

    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, cw, ch)

    proposals.forEach(p => (p.boxes?.length ? p.boxes : [p.bbox]).forEach(({ x, y, w, h }) => {
      if (!w || !h) return
      const rx = x * scaleX, ry = y * scaleY
      const rw = w * scaleX, rh = h * scaleY

      const isHovered  = hoveredId === p.id
      const color      = TYPE_COLOR[p.type] || TYPE_COLOR.default

      if (p.approved) {
        // Solid redaction preview
        ctx.fillStyle = isHovered ? color + 'dd' : color + '99'
        ctx.fillRect(rx, ry, rw, rh)

        // Label
        ctx.fillStyle = '#fff'
        ctx.font = `bold ${Math.max(9, rh * 0.22)}px IBM Plex Mono`
        ctx.textAlign = 'center'
        const label = p.type === 'face' ? 'FACE' : (p.label || 'REDACTED').slice(0, 14)
        ctx.fillText(label, rx + rw / 2, ry + rh / 2 + 4)
        ctx.textAlign = 'left'
      } else {
        // Dismissed — dashed outline only
        ctx.setLineDash([4, 3])
        ctx.strokeStyle = color + '55'
        ctx.lineWidth = 1.5
        ctx.strokeRect(rx, ry, rw, rh)
        ctx.setLineDash([])
      }

      // Hover ring
      if (isHovered) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.strokeRect(rx - 1, ry - 1, rw + 2, rh + 2)
      }
    }))
  }, [proposals, hoveredId, imgW, imgH])

  const toggle = (id) => {
    setProposals(prev => prev.map(p =>
      p.id === id ? { ...p, approved: !p.approved } : p
    ))
  }

  const approveAll  = () => setProposals(prev => prev.map(p => ({ ...p, approved: true  })))
  const dismissAll  = () => setProposals(prev => prev.map(p => ({ ...p, approved: false })))
  const approveSensitive = () => setProposals(prev => prev.map(p => ({ ...p, approved: p.sensitive })))

  const handleApply = async () => {
    setApplying(true)
    setError(null)
    try {
      const approvedBoxes = proposals
        .filter(p => p.approved)
        .flatMap(p => (p.boxes?.length ? p.boxes : [p.bbox]))
        .filter(b => b.w > 0 && b.h > 0)

      const resp = await applyRedactions(data.session_token, approvedBoxes, redactStyle)
      setResult(resp.data)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setApplying(false)
    }
  }

  const approvedCount  = proposals.filter(p => p.approved).length
  const sensitiveCount = proposals.filter(p => p.sensitive).length
  const safeCount      = proposals.filter(p => !p.sensitive).length

  const filteredProposals = proposals.filter(p => {
    if (filterMode === 'sensitive') return p.sensitive
    if (filterMode === 'safe')      return !p.sensitive
    return true
  })

  // ── Done state ─────────────────────────────────────────────────────────────
  if (result) {
    return (
      <div className={styles.done}>
        <div className={styles.doneIcon}>✓</div>
        <h2 className={styles.doneTitle}>{result.applied_count} Redactions Applied</h2>
        <p className={styles.doneSub}>Your redacted image is ready to download.</p>
        <div className={styles.doneActions}>
          <a href={downloadUrl(result.redacted_file)} className={styles.dlBtn} download>
            ⬇ DOWNLOAD REDACTED IMAGE
          </a>
          <button className={styles.resetBtn} onClick={onReset}>↺ NEW SCAN</button>
        </div>
        {result.redacted_b64 && (
          <img
            src={`data:image/jpeg;base64,${result.redacted_b64}`}
            className={styles.donePreview}
            alt="Redacted"
          />
        )}
      </div>
    )
  }

  return (
    <div className={styles.board}>
      {/* Header */}
      <div className={styles.boardHead}>
        <div>
          <h2 className={styles.boardTitle}>Human Review</h2>
          <p className={styles.boardSub}>
            Found <span className={styles.hi}>{sensitiveCount} sensitive</span> and{' '}
            <span className={styles.safe}>{safeCount} low-risk</span> items.
            Toggle to correct mistakes.
          </p>
        </div>
        <div className={styles.headActions}>
          <button className={styles.btnSm} onClick={approveSensitive}>Suggested</button>
          <button className={styles.btnSm} onClick={approveAll}>Approve All</button>
          <button className={`${styles.btnSm} ${styles.btnDim}`} onClick={dismissAll}>Dismiss All</button>
          <select className={styles.btnSm} value={redactStyle} onChange={e => setRedactStyle(e.target.value)}
                  title="Redaction style">
            {STYLES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className={styles.layout}>
        {/* Image canvas */}
        <div className={styles.imageWrap}>
          <img
            ref={imageRef}
            src={src}
            alt="Original"
            className={styles.origImg}
            onLoad={() => {
              const canvas = canvasRef.current
              if (canvas) {
                canvas.width  = imageRef.current.offsetWidth
                canvas.height = imageRef.current.offsetHeight
                // trigger redraw
                setProposals(p => [...p])
              }
            }}
          />
          <canvas
            ref={canvasRef}
            className={styles.overlay}
          />
          <div className={styles.imgLabel}>
            <span className={styles.dot} style={{ background: '#ff3356' }} /> Face
            <span className={styles.dot} style={{ background: '#ffb300', marginLeft: 10 }} /> Text PII
            <span className={styles.approvedBadge}>{approvedCount} will be redacted</span>
          </div>
        </div>

        {/* Proposal list */}
        <div className={styles.sidebar}>
          {/* Filter tabs */}
          <div className={styles.filters}>
            {['all','sensitive','safe'].map(f => (
              <button
                key={f}
                className={`${styles.filter} ${filterMode === f ? styles.filterActive : ''}`}
                onClick={() => setFilterMode(f)}
              >
                {f === 'all' ? `All (${proposals.length})` :
                 f === 'sensitive' ? `⚠ Sensitive (${sensitiveCount})` :
                 `✓ Low-risk (${safeCount})`}
              </button>
            ))}
          </div>

          <div className={styles.list}>
            {filteredProposals.length === 0 && (
              <div className={styles.empty}>No items in this filter</div>
            )}
            {filteredProposals.map(p => {
              const color = TYPE_COLOR[p.type] || TYPE_COLOR.default
              return (
                <div
                  key={p.id}
                  className={`${styles.item} ${p.approved ? styles.itemApproved : styles.itemDismissed}`}
                  style={{ borderLeftColor: p.approved ? color : 'var(--border)' }}
                  onMouseEnter={() => setHoveredId(p.id)}
                  onMouseLeave={() => setHoveredId(null)}
                >
                  <div className={styles.itemTop}>
                    <div className={styles.itemMeta}>
                      <span className={styles.itemLabel}>{p.label || p.type}</span>
                      {p.value && <span className={styles.itemValue}>"{p.value}"</span>}
                      <span
                        className={styles.itemBadge}
                        style={{
                          color:        p.sensitive ? '#ff3356' : '#00e676',
                          borderColor:  p.sensitive ? 'rgba(255,51,86,.3)' : 'rgba(0,230,118,.3)',
                          background:   p.sensitive ? 'rgba(255,51,86,.06)' : 'rgba(0,230,118,.06)',
                        }}
                      >
                        {p.sensitive ? '⚠ SENSITIVE' : '✓ LOW-RISK'} {Math.round((p.confidence ?? 0) * 100)}%
                      </span>
                    </div>
                    <button
                      className={`${styles.toggle} ${p.approved ? styles.toggleOn : styles.toggleOff}`}
                      onClick={() => toggle(p.id)}
                      title={p.approved ? 'Click to un-redact' : 'Click to redact'}
                    >
                      {p.approved ? 'REDACT ✓' : 'SKIP ✕'}
                    </button>
                  </div>

                  {p.reason && (
                    <div className={styles.reason}>
                      <span className={styles.reasonIcon}>ⓘ</span> {p.reason}
                    </div>
                  )}

                  {p.context && (
                    <div className={styles.context}>
                      …{p.context.slice(0, 100)}…
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Apply button */}
          <div className={styles.applyWrap}>
            {error && <div className={styles.error}>{error}</div>}
            <button
              className={styles.applyBtn}
              onClick={handleApply}
              disabled={applying || approvedCount === 0}
            >
              {applying
                ? <><span className={styles.spinner} /> APPLYING...</>
                : `▣ APPLY ${approvedCount} REDACTION${approvedCount !== 1 ? 'S' : ''} & EXPORT`
              }
            </button>
            {approvedCount === 0 && (
              <p className={styles.applyNote}>Approve at least one item to export</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
