// Shared between the service worker and the popup.
export const DEFAULTS = {
  apiBase: 'http://127.0.0.1:8765',
  pasteGuard: true,
  style: 'tag',              // 'tag' → [PHONE], 'mask' → ██████
  disabledSites: [],
}

export async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(Object.keys(DEFAULTS))) }
}

export async function api(path, init = {}) {
  const { apiBase } = await getSettings()
  const res = await fetch(apiBase + path, init)
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}
