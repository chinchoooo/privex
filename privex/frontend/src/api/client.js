import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

const upload = (path, file, onProgress) => {
  const fd = new FormData(); fd.append('file', file)
  return api.post(path, fd, {
    onUploadProgress: e => e.total && onProgress?.(Math.round(e.loaded / e.total * 100)),
  })
}

export const scanText         = (text, style = 'mask') => api.post('/text/scan', { text, style })
export const proposeRedactions = (file, onProgress) => upload('/image/propose', file, onProgress)
export const loadSession      = (token) => api.get(`/image/session/${token}`)
export const applyRedactions  = (sessionToken, boxes, style = 'black') =>
  api.post('/image/apply', { session_token: sessionToken, boxes, style })
export const startAudioJob    = (file, onProgress) => upload('/audio', file, onProgress)
export const startVideoJob    = (file, onProgress) => upload('/video', file, onProgress)
export const getJob           = (id) => api.get(`/jobs/${id}`)
export const checkHealth      = () => api.get('/health')
export const downloadUrl      = (file) => `/api/files/${file}`

/** Poll a background job until it finishes. onUpdate receives each job snapshot. */
export async function waitForJob(id, onUpdate, intervalMs = 700) {
  for (;;) {
    const { data } = await getJob(id)
    onUpdate?.(data)
    if (data.status === 'done') return data.result
    if (data.status === 'error') throw new Error(data.error || 'Job failed')
    await new Promise(r => setTimeout(r, intervalMs))
  }
}
