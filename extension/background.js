import { api, getSettings } from './shared.js'

// Content scripts can't call the loopback API directly (page-origin CORS), so they go through here.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === 'scanText') {
    getSettings()
      .then(s => api('/api/text/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: msg.text, style: s.style }),
      }))
      .then(result => reply({ ok: true, result }))
      .catch(e => reply({ ok: false, error: String(e.message || e) }))
    return true   // async reply
  }
  if (msg.type === 'getSettings') {
    getSettings().then(reply)
    return true
  }
})

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'privex-image', title: 'Redact this image with PRIVEX', contexts: ['image'] })
  chrome.contextMenus.create({ id: 'privex-text', title: 'Check selection for personal data', contexts: ['selection'] })
})

function notify(title, message) {
  chrome.notifications.create({ type: 'basic', iconUrl: 'icons/icon128.png', title, message })
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === 'privex-image') {
      if (info.srcUrl.startsWith('blob:')) throw new Error('This image is a page-local blob; save it and upload it in the app instead.')
      const img = await fetch(info.srcUrl, { credentials: 'include' })
      if (!img.ok) throw new Error(`Could not download image (${img.status})`)
      const blob = await img.blob()
      const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace('svg+xml', 'svg')
      const fd = new FormData()
      fd.append('file', blob, `image.${ext}`)
      const { apiBase } = await getSettings()
      const res = await api('/api/image/propose', { method: 'POST', body: fd })
      chrome.tabs.create({ url: `${apiBase}/#review/${res.session_token}` })
    }

    if (info.menuItemId === 'privex-text') {
      const s = await getSettings()
      const result = await api('/api/text/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: info.selectionText, style: s.style }),
      })
      chrome.tabs.sendMessage(tab.id, { type: 'showScan', result })
    }
  } catch (e) {
    const offline = /Failed to fetch|NetworkError/i.test(String(e))
    notify('PRIVEX', offline ? 'The PRIVEX app is not running. Start it and try again.' : String(e.message || e))
  }
})
