// Correção Pro - service worker
const MAX_HISTORY = 500;

async function addToHistory(text) {
  text = (text || '').trim();
  if (!text) return;
  const { history = [] } = await chrome.storage.local.get('history');
  const filtered = history.filter(h => h.text !== text); // evita duplicadas
  filtered.unshift({ id: crypto.randomUUID(), text, date: Date.now() });
  await chrome.storage.local.set({ history: filtered.slice(0, MAX_HISTORY) });
}

chrome.runtime.onInstalled.addListener(async () => {
  const data = await chrome.storage.local.get(['history', 'shortcuts', 'settings']);
  await chrome.storage.local.set({
    history: data.history || [],
    shortcuts: data.shortcuts || {},
    settings: data.settings || { trigger: 'space', enabled: true }
  });
  chrome.contextMenus.create({ id: 'cp-save', title: 'Correção Pro: salvar seleção', contexts: ['selection'] });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === 'cp-save') addToHistory(info.selectionText);
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'copy') addToHistory(msg.text);
});
