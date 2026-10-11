import { useState, useEffect } from 'react'
import Header       from './components/Header.jsx'
import Pipeline     from './components/Pipeline.jsx'
import UploadPanel  from './components/UploadPanel.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import ReviewBoard  from './components/ReviewBoard.jsx'
import LogTerminal  from './components/LogTerminal.jsx'
import { useScan }  from './hooks/useScan.js'
import { proposeRedactions, loadSession, checkHealth } from './api/client.js'
import styles from './App.module.css'

export default function App() {
  const { stage, result, error, progress, logs, run, reset } = useScan()

  const [reviewData,   setReviewData]   = useState(null)
  const [proposing,    setProposing]    = useState(false)
  const [proposeError, setProposeError] = useState(null)
  const [proposeLog,   setProposeLog]   = useState([])
  const [activeMode,   setActiveMode]   = useState(null)
  const [health,       setHealth]       = useState(null)

  const scanning = stage && stage !== 'done' && stage !== 'error'

  const log = (lvl, msg) => setProposeLog(l => [...l, { level: lvl, msg, ts: new Date().toLocaleTimeString() }])

  useEffect(() => {
    checkHealth().then(r => setHealth(r.data)).catch(() => setHealth(false))
  }, [])

  // The Chrome extension opens the app at #review/<session_token> after uploading an image.
  useEffect(() => {
    const open = () => {
      const m = window.location.hash.match(/^#review\/([a-f0-9]{32})$/)
      if (!m) return
      setActiveMode('image'); setProposing(true); setProposeError(null)
      log('info', 'Loading image sent from the browser extension…')
      loadSession(m[1])
        .then(r => setReviewData(r.data))
        .catch(e => setProposeError(e.response?.data?.detail || e.message))
        .finally(() => setProposing(false))
    }
    open()
    window.addEventListener('hashchange', open)
    return () => window.removeEventListener('hashchange', open)
  }, [])

  const handleScan = async (mode, payload) => {
    setActiveMode(mode)
    if (mode !== 'image') { run(mode, payload); return }

    setProposing(true); setProposeError(null); setReviewData(null); setProposeLog([])
    try {
      log('info', 'Uploading image…')
      log('info', 'Running face detection + OCR + PII recognizers…')
      const resp = await proposeRedactions(payload)
      log('info', `${resp.data.proposals?.length ?? 0} candidates found`)
      log('info', `${resp.data.sensitive_count} sensitive · ${resp.data.safe_count} low-risk — ready for review`)
      setReviewData(resp.data)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      setProposeError(msg); log('error', `Failed: ${msg}`)
    } finally {
      setProposing(false)
    }
  }

  const handleReset = () => {
    reset()
    setReviewData(null); setProposeError(null); setProposeLog([]); setActiveMode(null)
    if (window.location.hash) history.replaceState(null, '', window.location.pathname)
  }

  const showReview  = activeMode === 'image' && (reviewData || proposing || proposeError)
  const showResults = activeMode !== 'image' && (result || stage)
  const pipeStage   = proposing ? 'detect' : reviewData ? 'review' : stage
  const engines     = health?.engines

  return (
    <div className={styles.app}>
      <Header health={health} />

      <main className={styles.main}>
        <div className={styles.hero}>
          <p className={styles.tag}>// LOCAL-ONLY · NO LLM · HUMAN-IN-THE-LOOP</p>
          <h1 className={styles.h1}>
            Detect. Review.<br />
            <span className={styles.accent}>Redact.</span>
          </h1>
        </div>

        {engines && (
          <div className={styles.llmBar}>
            <span className={styles.llmBadge}>⬡ ON-DEVICE</span>
            <span className={styles.engineList}>
              NER {engines.ner ?? 'off'} · face {engines.face ?? 'off'} · {engines.ocr} · {engines.asr}
            </span>
          </div>
        )}

        <Pipeline stage={pipeStage} />

        {!reviewData ? (
          <>
            <div className={styles.grid}>
              <UploadPanel onScan={handleScan} scanning={scanning || proposing} progress={progress}
                           maxMb={health?.max_upload_mb} />

              {showResults ? (
                <ResultsPanel result={result} stage={stage} progress={progress} />
              ) : (
                <div className={styles.reviewHint}>
                  <span className={styles.hintIcon}>👁</span>
                  <p className={styles.hintTitle}>Human-in-the-Loop Review</p>
                  <p className={styles.hintSub}>
                    For images: PRIVEX proposes redactions and explains each one.<br />
                    You approve or dismiss before anything is changed.<br />
                    Video, audio and text are processed automatically.
                  </p>
                  <div className={styles.hintSteps}>
                    <div className={styles.step}><span>1</span> Detect faces + text</div>
                    <div className={styles.step}><span>2</span> Explain each finding</div>
                    <div className={styles.step}><span>3</span> You approve or dismiss</div>
                    <div className={styles.step}><span>4</span> Apply & download</div>
                  </div>
                </div>
              )}
            </div>

            {proposeError && (
              <div className={styles.errorBanner}>
                <span>⚠ {proposeError}</span>
                <button onClick={handleReset} className={styles.errClose}>✕</button>
              </div>
            )}
          </>
        ) : (
          <ReviewBoard data={reviewData} onReset={handleReset} />
        )}

        <LogTerminal logs={showReview && !reviewData ? proposeLog : logs} />

        {!reviewData && (result || error) && (
          <div className={styles.resetRow}>
            <button className={styles.resetBtn} onClick={handleReset}>↺ NEW SCAN</button>
          </div>
        )}
      </main>

      <footer className={styles.footer}>
        PRIVEX {health?.version ?? ''} · runs entirely on this computer · RapidOCR + YuNet + spaCy + faster-whisper
      </footer>
    </div>
  )
}
