import { api, getSettings } from './shared.js'

const $ = id => document.getElementById(id)
let settings = await getSettings()
let host = ''

try {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  host = new URL(tab.url).hostname
} catch {}
$('host').textContent = host || 'this site'
$('siteOn').disabled = !host

const render = () => {
  $('pasteGuard').checked = settings.pasteGuard
  $('siteOn').checked = !settings.disabledSites.includes(host)
  $('style').value = settings.style
}
render()

const save = async patch => {
  settings = { ...settings, ...patch }
  await chrome.storage.sync.set(patch)
  render()
}

$('pasteGuard').onchange = e => save({ pasteGuard: e.target.checked })
$('style').onchange = e => save({ style: e.target.value })
$('siteOn').onchange = e => save({
  disabledSites: e.target.checked
    ? settings.disabledSites.filter(h => h !== host)
    : [...new Set([...settings.disabledSites, host])],
})

api('/api/health')
  .then(h => { $('status').textContent = `● engine ${h.version}`; $('status').className = 'status ok' })
  .catch(() => {
    $('status').textContent = '✕ app not running'; $('status').className = 'status off'
    $('help').textContent = 'Start the PRIVEX app (PRIVEX.exe) — the extension needs it running on this computer.'
  })

$('scan').onclick = async () => {
  const text = $('text').value
  if (!text.trim()) return
  $('out').hidden = false
  $('out').textContent = 'Checking…'
  try {
    const r = await api('/api/text/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, style: settings.style }),
    })
    const types = [...new Set(r.entities.filter(e => e.sensitive).map(e => e.label))]
    $('out').textContent = r.sensitive
      ? `${r.entity_count} sensitive: ${types.join(', ')}\n\n${r.redacted_text}`
      : 'No personal data found.'
    $('copy').hidden = !r.sensitive
    $('copy').onclick = () => navigator.clipboard.writeText(r.redacted_text)
  } catch (e) {
    $('out').textContent = `Error: ${e.message}`
  }
}

$('open').onclick = () => chrome.tabs.create({ url: settings.apiBase })
