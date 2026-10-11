import { useState, useCallback } from 'react'
import { scanText, startAudioJob, startVideoJob, waitForJob } from '../api/client'

// Map backend job progress (0..1) onto the pipeline stages shown in the UI.
const stageFor = p => (p < 0.1 ? 'upload' : p < 0.6 ? 'detect' : p < 0.95 ? 'redact' : 'done')

export function useScan() {
  const [stage,    setStage]    = useState(null)   // null | upload | detect | classify | redact | done | error
  const [result,   setResult]   = useState(null)
  const [error,    setError]    = useState(null)
  const [progress, setProgress] = useState(0)
  const [logs,     setLogs]     = useState([])

  const addLog = useCallback((level, msg) => {
    setLogs(prev => [...prev, { level, msg, ts: new Date().toLocaleTimeString() }])
  }, [])

  const run = useCallback(async (mode, payload) => {
    setResult(null); setError(null); setLogs([]); setProgress(0)
    try {
      setStage('upload')
      addLog('info', `Starting ${mode} scan (local, no LLM)…`)
      let data

      if (mode === 'text') {
        setStage('detect')
        data = (await scanText(payload)).data
      } else {
        const start = mode === 'audio' ? startAudioJob : startVideoJob
        const { data: job } = await start(payload, p => setProgress(p))
        addLog('info', `Uploaded — job ${job.id.slice(0, 8)} queued`)
        let lastMsg = ''
        data = await waitForJob(job.id, j => {
          setProgress(Math.round(j.progress * 100))
          setStage(stageFor(j.progress))
          if (j.message && j.message !== lastMsg && !/^reading text|^redacting frame/.test(j.message)) {
            addLog('info', j.message); lastMsg = j.message
          }
        })
      }

      setStage('done')
      addLog('info', `Scan complete — ${data.entity_count ?? 0} sensitive items`)
      addLog(data.sensitive ? 'warn' : 'info',
        data.sensitive ? 'Sensitive data found — redacted output ready' : 'No sensitive data detected')
      setResult({ ...data, mode })
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || 'Unknown error'
      setStage('error'); setError(msg)
      addLog('error', `Scan failed: ${msg}`)
    }
  }, [addLog])

  const reset = useCallback(() => {
    setStage(null); setResult(null); setError(null); setProgress(0); setLogs([])
  }, [])

  return { stage, result, error, progress, logs, run, reset }
}
