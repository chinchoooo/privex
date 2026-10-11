// PRIVEX paste guard: intercepts pastes into editable fields, checks them with the local
// PRIVEX engine, and offers to paste a redacted version when personal data is found.
(() => {
  const MIN_LEN = 6
  let settings = null
  let banner = null

  const send = msg => new Promise(resolve => chrome.runtime.sendMessage(msg, resolve))
  const refresh = async () => { settings = await send({ type: 'getSettings' }) }
  refresh()
  chrome.storage.onChanged.addListener(refresh)

  const enabledHere = () =>
    settings?.pasteGuard && !(settings.disabledSites || []).includes(location.hostname)

  const isEditable = el =>
    el && (el.isContentEditable || el.tagName === 'TEXTAREA' ||
           (el.tagName === 'INPUT' && /^(text|search|email|url|tel|)$/i.test(el.type)))

  function insertText(target, text) {
    target.focus()
    // execCommand keeps undo history and fires the input events frameworks (React etc.) listen to.
    if (!document.execCommand('insertText', false, text)) {
      if ('value' in target) {
        const s = target.selectionStart ?? target.value.length
        const e = target.selectionEnd ?? s
        target.setRangeText(text, s, e, 'end')
        target.dispatchEvent(new Event('input', { bubbles: true }))
      }
    }
  }

  function closeBanner() { banner?.remove(); banner = null }

  function showBanner(target, result, original, savedRange) {
    closeBanner()
    const types = [...new Set(result.entities.filter(e => e.sensitive).map(e => e.label))]
    banner = document.createElement('div')
    banner.className = 'privex-banner'
    banner.innerHTML = `
      <div class="privex-title">🛡 PRIVEX found ${result.entity_count} sensitive item${result.entity_count === 1 ? '' : 's'}</div>
      <div class="privex-types"></div>
      <pre class="privex-preview"></pre>
      <div class="privex-actions">
        <button data-act="redacted" class="privex-primary">Paste redacted</button>
        <button data-act="original">Paste original</button>
        <button data-act="cancel">Cancel</button>
      </div>`
    banner.querySelector('.privex-types').textContent = types.join(' · ')
    banner.querySelector('.privex-preview').textContent = result.redacted_text.slice(0, 400)

    const r = target.getBoundingClientRect()
    banner.style.top = `${Math.max(8, Math.min(window.innerHeight - 260, r.bottom + 8))}px`
    banner.style.left = `${Math.max(8, Math.min(window.innerWidth - 380, r.left))}px`

    // mousedown preventDefault keeps focus/selection in the editor
    banner.addEventListener('mousedown', e => e.preventDefault())
    banner.addEventListener('click', e => {
      const act = e.target?.dataset?.act
      if (!act) return
      closeBanner()
      if (act === 'cancel') return
      restoreSelection(savedRange)
      insertText(target, act === 'redacted' ? result.redacted_text : original)
    })
    document.documentElement.appendChild(banner)
  }

  function saveSelection() {
    const sel = window.getSelection()
    return sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null
  }
  function restoreSelection(range) {
    if (!range) return
    const sel = window.getSelection()
    sel.removeAllRanges(); sel.addRange(range)
  }

  function toast(text, ms = 3500) {
    const t = document.createElement('div')
    t.className = 'privex-toast'
    t.textContent = text
    document.documentElement.appendChild(t)
    setTimeout(() => t.remove(), ms)
  }

  document.addEventListener('paste', async e => {
    const target = e.target.closest?.('[contenteditable=""], [contenteditable="true"], textarea, input') || e.target
    if (!enabledHere() || !isEditable(target)) return
    const text = e.clipboardData?.getData('text/plain') || ''
    if (text.trim().length < MIN_LEN) return

    e.preventDefault()
    e.stopImmediatePropagation()
    const savedRange = saveSelection()
    const resp = await send({ type: 'scanText', text })

    if (!resp?.ok) {
      // Fail open so the page stays usable, but say so.
      restoreSelection(savedRange)
      insertText(target, text)
      toast('PRIVEX engine is not running — pasted without checking.')
      return
    }
    if (!resp.result.sensitive) {
      restoreSelection(savedRange)
      insertText(target, text)
      return
    }
    showBanner(target, resp.result, text, savedRange)
  }, true)

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBanner() }, true)

  chrome.runtime.onMessage.addListener(msg => {
    if (msg.type !== 'showScan') return
    const r = msg.result
    if (!r.sensitive) { toast('PRIVEX: no personal data found in the selection.'); return }
    const types = [...new Set(r.entities.filter(e => e.sensitive).map(e => e.label))]
    toast(`PRIVEX: ${r.entity_count} sensitive item(s) — ${types.join(', ')}`, 6000)
  })
})()
