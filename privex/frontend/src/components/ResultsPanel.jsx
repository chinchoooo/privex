import { useState } from 'react'
import { downloadUrl } from '../api/client'
import styles from './ResultsPanel.module.css'

const TYPE_COLORS = { face: '#ff3356', text: '#ffb300', pii: '#00e676', llm: '#c97bff', regex: '#4488ff' }
const TYPE_ICONS  = { face: '👤', text: '🔤', pii: '🔑', llm: '🧠', regex: '⚙' }

function RiskMeter({ count }) {
  const score = Math.min(100, count * 14)
  const cls   = score > 65 ? 'high' : score > 30 ? 'med' : 'low'
  return (
    <div className={styles.riskRow}>
      <span className={styles.riskLabel}>RISK</span>
      <div className={styles.riskTrack}>
        <div className={`${styles.riskFill} ${styles[cls]}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`${styles.riskScore} ${styles[cls]}`}>{score}</span>
    </div>
  )
}

export default function ResultsPanel({ result, stage, progress }) {
  const [dismissed, setDismissed] = useState(new Set())
  const [revealed,  setRevealed]  = useState(new Set())

  if (!result && stage !== 'done') {
    return (
      <div className={styles.card}>
        <div className={styles.head}>
          <span className={styles.title}>// RESULTS</span>
          <span className={`${styles.badge} ${styles.idle}`}>{stage ? `${progress ?? 0}%` : 'WAITING'}</span>
        </div>
        <div className={styles.empty}>
          <span className={styles.emptyIcon}>◈</span>
          <p>{stage ? 'Processing locally — large videos can take a few minutes' : 'Run a scan to see results'}</p>
        </div>
      </div>
    )
  }

  const detections = (result?.detections || result?.entities || []).filter(d => d.sensitive !== false)
  const visible    = detections.filter((_, i) => !dismissed.has(i))
  const isSensitive = result?.sensitive

  // Build text with redaction spans
  const renderText = () => {
    if (!result?.redacted_text) return null
    // Replace ██ blocks with toggleable spans
    const parts = result.redacted_text.split(/(█+)/g)
    let key = 0
    return parts.map(part => {
      if (/^█+$/.test(part)) {
        const k = key++
        const show = revealed.has(k)
        return (
          <span
            key={k}
            className={`${styles.redacted} ${show ? styles.revealed : ''}`}
            onClick={() => setRevealed(prev => {
              const n = new Set(prev); show ? n.delete(k) : n.add(k); return n
            })}
            title={show ? 'Click to hide' : 'Click to reveal'}
          >
            {show ? '(visible)' : part}
          </span>
        )
      }
      return <span key={`t${key++}`}>{part}</span>
    })
  }

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={styles.title}>// RESULTS</span>
        <span className={`${styles.badge} ${isSensitive ? styles.danger : styles.ok}`}>
          {isSensitive ? `⚠ ${detections.length} FOUND` : '✓ CLEAN'}
        </span>
      </div>

      <div className={styles.body}>

        {/* Detection list */}
        <div className={styles.section}>
          <div className={styles.sectionLabel}>DETECTIONS</div>
          {visible.length === 0 ? (
            <div className={styles.noItems}>{isSensitive ? 'All dismissed' : 'No sensitive data detected'}</div>
          ) : (
            <div className={styles.list}>
              {detections.map((det, i) => {
                if (dismissed.has(i)) return null
                const type   = det.type || det.source || 'pii'
                const color  = TYPE_COLORS[type] || TYPE_COLORS.pii
                const icon   = TYPE_ICONS[type] || '⚠'
                const label  = det.label || det.text || type
                const sub    = [det.text && det.text !== label ? `"${det.text}"` : null, det.reason || det.source]
                                 .filter(Boolean).join(' — ')
                const conf   = det.score ?? det.confidence ?? null
                return (
                  <div key={i} className={styles.det} style={{ borderLeftColor: color, animationDelay: `${i * 50}ms` }}>
                    <span className={styles.detIcon}>{icon}</span>
                    <div className={styles.detBody}>
                      <div className={styles.detLabel}>{label}</div>
                      {sub && <div className={styles.detSub}>{sub}</div>}
                    </div>
                    {conf !== null && (
                      <span className={styles.detConf} style={{ color }}>{(conf * 100).toFixed(0)}%</span>
                    )}
                    <button className={styles.dismiss} onClick={() => setDismissed(p => new Set([...p, i]))}>✕</button>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Redacted text preview */}
        {result?.redacted_text && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>REDACTED OUTPUT <span className={styles.hint}>(click ██ to peek)</span></div>
            <div className={styles.textBox}>{renderText()}</div>
          </div>
        )}

        {/* Video-specific info */}
        {result?.mode === 'video' && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>VIDEO INFO</div>
            {result.thumbnail_b64 && (
              <img src={`data:image/jpeg;base64,${result.thumbnail_b64}`} alt="First redacted frame"
                   style={{ width: '100%', borderRadius: 4, marginBottom: 10 }} />
            )}
            <div className={styles.stats}>
              <div className={styles.stat}>
                <span style={{ color: 'var(--blue)' }}>{result.frames_processed ?? 0}</span><br/>Frames
              </div>
              <div className={styles.stat}>
                <span style={{ color: 'var(--blue)' }}>{result.duration_seconds ?? 0}s</span><br/>Duration
              </div>
              <div className={styles.stat}>
                <span style={{ color: 'var(--green)' }}>{result.face_detections ?? 0}</span><br/>Face Hits
              </div>
              <div className={styles.stat}>
                <span style={{ color: result.sensitive_values?.length > 0 ? 'var(--red)' : 'var(--green)' }}>
                  {result.sensitive_values?.length ?? 0}
                </span><br/>Text PII
              </div>
            </div>
            {result.sensitive_values?.length > 0 && (
              <div className={styles.muteList}>
                {result.sensitive_values.map((v, i) => (
                  <span key={i} className={styles.muteTag} style={{ borderColor: 'var(--red)' }}>🔴 {v}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* OCR text */}
        {result?.ocr_text && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>OCR EXTRACTED TEXT</div>
            <div className={styles.ocrBox}>{result.ocr_text}</div>
          </div>
        )}

        {/* Audio transcript */}
        {result?.transcript && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>TRANSCRIPT</div>
            <div className={styles.ocrBox}>{result.transcript}</div>
            {result.muted_segments?.length > 0 && (
              <div className={styles.muteList}>
                {result.muted_segments.map((s, i) => (
                  <span key={i} className={styles.muteTag}>
                    🔇 {s.start.toFixed(2)}s – {s.end.toFixed(2)}s
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Stats row */}
        <div className={styles.stats}>
          <div className={styles.stat}><span style={{ color: 'var(--red)'   }}>{result?.face_count ?? result?.face_detections ?? 0}</span><br/>Faces</div>
          <div className={styles.stat}><span style={{ color: 'var(--amber)' }}>{result?.text_redacted ?? result?.entity_count ?? 0}</span><br/>Text PII</div>
          <div className={styles.stat}><span style={{ color: 'var(--blue)'  }}>{result?.muted_count ?? result?.muted_segments?.length ?? 0}</span><br/>Audio Mutes</div>
          <div className={styles.stat}><span style={{ color: isSensitive ? 'var(--red)' : 'var(--green)' }}>{isSensitive ? 'HIGH' : 'LOW'}</span><br/>Risk</div>
        </div>

        <RiskMeter count={detections.length} />
      </div>

      {/* Download */}
      {result?.redacted_file && (
        <div className={styles.foot}>
          <a href={downloadUrl(result.redacted_file)} className={styles.dlBtn} download>
            ⬇ DOWNLOAD REDACTED FILE
          </a>
        </div>
      )}
    </div>
  )
}