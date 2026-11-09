// Correção Pro - captura cópias e expande atalhos
(() => {
  let shortcuts = {};
  let settings = { trigger: 'space', enabled: true };

  chrome.storage.local.get(['shortcuts', 'settings'], d => {
    shortcuts = d.shortcuts || {};
    settings = d.settings || settings;
  });
  chrome.storage.onChanged.addListener(ch => {
    if (ch.shortcuts) shortcuts = ch.shortcuts.newValue || {};
    if (ch.settings) settings = ch.settings.newValue || settings;
  });

  // ---- 1. Guardar cópias ----
  const onCopy = () => {
    let text = String(window.getSelection() || '');
    const el = document.activeElement;
    if (!text && el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT')) {
      try { text = el.value.substring(el.selectionStart, el.selectionEnd); } catch (_) {}
    }
    if (text.trim()) {
      try { chrome.runtime.sendMessage({ type: 'copy', text }); } catch (_) {}
    }
  };
  document.addEventListener('copy', onCopy, true);
  document.addEventListener('cut', onCopy, true);

  // ---- 2. Expandir atalhos ----
  const isTextInput = el =>
    el && (el.tagName === 'TEXTAREA' ||
      (el.tagName === 'INPUT' && /^(text|search|email|url|tel|)$/i.test(el.type || '')));

  // Retorna [atalho, texto] se a palavra que termina em `before` é um atalho
  function match(before) {
    const m = before.match(/(\S+)$/);
    if (!m) return null;
    const word = m[1];
    const key = Object.keys(shortcuts).find(k => k.toLowerCase() === word.toLowerCase());
    return key ? [word, shortcuts[key]] : null;
  }

  function expandInput(el, suffixLen) {
    const pos = el.selectionStart;
    if (pos !== el.selectionEnd) return;
    const before = el.value.slice(0, pos - suffixLen);
    const found = match(before);
    if (!found) return;
    const [word, text] = found;
    const start = before.length - word.length;
    el.setSelectionRange(start, before.length);
    // execCommand mantém o Ctrl+Z e dispara eventos para React/Vue etc.
    if (!document.execCommand('insertText', false, text)) {
      el.setRangeText(text, start, before.length, 'end');
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const end = start + text.length + suffixLen;
    el.setSelectionRange(end, end);
  }

  function expandEditable(suffixLen) {
    const sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return;
    const node = sel.anchorNode;
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const offset = sel.anchorOffset;
    const before = node.textContent.slice(0, offset - suffixLen);
    const found = match(before);
    if (!found) return;
    const [word, text] = found;
    const range = document.createRange();
    range.setStart(node, before.length - word.length);
    range.setEnd(node, before.length);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('insertText', false, text);
    if (suffixLen) { // reposiciona o cursor depois do espaço já digitado
      sel.modify && sel.modify('move', 'forward', 'character');
    }
  }

  let busy = false;
  document.addEventListener('input', e => {
    if (busy || !settings.enabled || e.isComposing) return;
    if (e.inputType && !e.inputType.startsWith('insert')) return;
    const el = e.target;
    const typed = e.data ?? '';
    let suffixLen;
    if (settings.trigger === 'immediate') suffixLen = 0;
    else if (/^\s$/.test(typed) || e.inputType === 'insertParagraph' || e.inputType === 'insertLineBreak') suffixLen = typed.length === 1 ? 1 : 0;
    else return;
    if (settings.trigger !== 'immediate' && suffixLen === 0) return; // Enter: não mexe para não quebrar formulários
    busy = true;
    try {
      if (isTextInput(el)) expandInput(el, suffixLen);
      else if (el.isContentEditable) expandEditable(suffixLen);
    } finally { busy = false; }
  }, true);
})();
