import { useState, useRef } from 'react'
import styles from './UploadPanel.module.css'

const MODES = [
  { id: 'image', label: 'Image', icon: '🖼', accept: 'image/*',                hint: 'PNG, JPG, WEBP' },
  { id: 'video', label: 'Video', icon: '🎬', accept: 'video/*,.mp4,.mov',      hint: 'MP4, MOV, MKV, WEBM'  },
  { id: 'audio', label: 'Audio', icon: '🎙', accept: 'audio/*,.wav,.m4a,.flac', hint: 'WAV, MP3, M4A, OGG, FLAC' },
  { id: 'text',  label: 'Text',  icon: '📄', accept: null,            hint: 'Paste any text'  },
]

export default function UploadPanel({ onScan, scanning, progress, maxMb }) {
  const [mode,     setMode]     = useState('image')
  const [file,     setFile]     = useState(null)
  const [text,     setText]     = useState('')
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  const current = MODES.find(m => m.id === mode)
  const canScan = !scanning && (mode === 'text' ? text.trim().length > 0 : file !== null)

  const handleFile = f => { if (f) setFile(f) }
  const handleDrop = e => {
    e.preventDefault(); setDragging(false)
    handleFile(e.dataTransfer.files[0])
  }

  const handleScan = () => {
    if (!canScan) return
    onScan(mode, mode === 'text' ? text : file)
  }

  const handleModeSwitch = m => {
    setMode(m); setFile(null); setText('')
  }

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={styles.title}>// INPUT</span>
        <span className={`${styles.badge} ${file || text ? styles.ready : styles.idle}`}>
          {file ? file.name.slice(0,24) + (file.name.length > 24 ? '…' : '') : text ? 'TEXT READY' : 'WAITING'}
        </span>
      </div>

      <div className={styles.body}>
        {/* Mode tabs */}
        <div className={styles.tabs}>
          {MODES.map(m => (
            <button
              key={m.id}
              className={`${styles.tab} ${mode === m.id ? styles.active : ''}`}
              onClick={() => handleModeSwitch(m.id)}
            >
              {m.icon} {m.label}
            </button>
          ))}
        </div>

        {/* Drop zone (image / audio) */}
        {mode !== 'text' && (
          <div
            className={`${styles.drop} ${dragging ? styles.over : ''} ${file ? styles.hasFile : ''}`}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <input
              ref={inputRef}
              type="file"
              accept={current.accept}
              style={{ display: 'none' }}
              onChange={e => handleFile(e.target.files[0])}
            />
            {file ? (
              <div className={styles.fileInfo}>
                <span className={styles.fileIcon}>{current.icon}</span>
                <div>
                  <div className={styles.fileName}>{file.name}</div>
                  <div className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</div>
                </div>
                <button className={styles.clearBtn} onClick={e => { e.stopPropagation(); setFile(null) }}>✕</button>
              </div>
            ) : (
              <>
                <span className={styles.dropIcon}>{current.icon}</span>
                <p className={styles.dropTitle}>Drop {current.label.toLowerCase()} here</p>
                <p className={styles.dropHint}>{current.hint}{maxMb ? ` · up to ${maxMb} MB` : ''}</p>
              </>
            )}
          </div>
        )}

        {/* Text area */}
        {mode === 'text' && (
          <textarea
            className={styles.textarea}
            placeholder="Paste text to scan for PII — names, phone numbers, IDs, bank details..."
            value={text}
            onChange={e => setText(e.target.value)}
            rows={6}
          />
        )}

        {/* Scan button */}
        <button className={styles.scanBtn} onClick={handleScan} disabled={!canScan}>
          {scanning ? (
            <>
              <span className={styles.spinner} />
              {progress > 0 && progress < 100 ? `WORKING ${progress}%` : 'SCANNING...'}
            </>
          ) : '⬡ SCAN FOR PRIVACY RISKS'}
        </button>
      </div>
    </div>
  )
}
