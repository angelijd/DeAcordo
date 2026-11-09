const $ = s => document.querySelector(s);
const get = keys => chrome.storage.local.get(keys);
const set = obj => chrome.storage.local.set(obj);
const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Abas
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button, .tab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('#' + b.dataset.tab).classList.add('active');
});

// Histórico
async function renderHistory() {
  const { history = [], shortcuts = {} } = await get(['history', 'shortcuts']);
  const q = $('#search').value.toLowerCase();
  const items = history.filter(h => h.text.toLowerCase().includes(q));
  const used = new Map(Object.entries(shortcuts).map(([k, v]) => [v, k]));
  $('#historyList').innerHTML = items.length ? items.map(h => `
    <li data-id="${h.id}">
      <div class="text">${esc(h.text)}</div>
      <div class="meta">
        <span>${new Date(h.date).toLocaleString('pt-BR')}${used.has(h.text) ? ` · <b class="key">${esc(used.get(h.text))}</b>` : ''}</span>
        <button class="small ghost" data-act="copy">Copiar</button>
        <button class="small" data-act="assign">Criar atalho</button>
        <button class="small danger" data-act="del">✕</button>
      </div>
    </li>`).join('') : '<p class="empty">Nenhuma cópia ainda. Copie algum texto (Ctrl+C) em qualquer site.</p>';
}

$('#historyList').onclick = async e => {
  const act = e.target.dataset.act; if (!act) return;
  const id = e.target.closest('li').dataset.id;
  const { history = [], shortcuts = {} } = await get(['history', 'shortcuts']);
  const item = history.find(h => h.id === id);
  if (act === 'copy') { await navigator.clipboard.writeText(item.text); e.target.textContent = 'Copiado!'; }
  if (act === 'del') { await set({ history: history.filter(h => h.id !== id) }); renderHistory(); }
  if (act === 'assign') {
    const key = prompt('Digite o atalho para este texto (sem espaços):');
    if (!key || /\s/.test(key)) return;
    if (shortcuts[key] && !confirm(`O atalho "${key}" já existe. Substituir?`)) return;
    shortcuts[key.trim()] = item.text;
    await set({ shortcuts }); renderHistory(); renderShortcuts();
  }
};
$('#search').oninput = renderHistory;
$('#clearHistory').onclick = async () => { if (confirm('Apagar todo o histórico de cópias?')) { await set({ history: [] }); renderHistory(); } };

// Atalhos
async function renderShortcuts() {
  const { shortcuts = {} } = await get('shortcuts');
  const keys = Object.keys(shortcuts).sort();
  $('#shortcutList').innerHTML = keys.length ? keys.map(k => `
    <li data-key="${esc(k)}">
      <div class="key">${esc(k)}</div>
      <div class="text">${esc(shortcuts[k])}</div>
      <div class="meta"><span></span>
        <button class="small ghost" data-act="edit">Editar</button>
        <button class="small danger" data-act="del">✕</button>
      </div>
    </li>`).join('') : '<p class="empty">Nenhum atalho. Crie um acima ou a partir de uma cópia.</p>';
}

$('#shortcutForm').onsubmit = async e => {
  e.preventDefault();
  const key = $('#key').value.trim(), value = $('#value').value;
  const { shortcuts = {} } = await get('shortcuts');
  shortcuts[key] = value;
  await set({ shortcuts });
  $('#key').value = $('#value').value = '';
  renderShortcuts();
};

$('#shortcutList').onclick = async e => {
  const act = e.target.dataset.act; if (!act) return;
  const key = e.target.closest('li').dataset.key;
  const { shortcuts = {} } = await get('shortcuts');
  if (act === 'edit') { $('#key').value = key; $('#value').value = shortcuts[key]; $('#value').focus(); }
  if (act === 'del' && confirm(`Excluir o atalho "${key}"?`)) { delete shortcuts[key]; await set({ shortcuts }); renderShortcuts(); }
};

// Configurações
async function loadSettings() {
  const { settings = { trigger: 'space', enabled: true } } = await get('settings');
  $('#enabled').checked = settings.enabled;
  document.querySelector(`input[name=trigger][value=${settings.trigger}]`).checked = true;
}
async function saveSettings() {
  await set({ settings: { enabled: $('#enabled').checked, trigger: document.querySelector('input[name=trigger]:checked').value } });
}
$('#enabled').onchange = saveSettings;
document.querySelectorAll('input[name=trigger]').forEach(r => r.onchange = saveSettings);

$('#export').onclick = async () => {
  const data = await get(['history', 'shortcuts', 'settings']);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  a.download = 'correcao-pro-backup.json'; a.click();
};
$('#import').onchange = async e => {
  try {
    const data = JSON.parse(await e.target.files[0].text());
    await set({ history: data.history || [], shortcuts: data.shortcuts || {}, ...(data.settings && { settings: data.settings }) });
    alert('Backup importado!'); renderHistory(); renderShortcuts(); loadSettings();
  } catch { alert('Arquivo inválido.'); }
};

renderHistory(); renderShortcuts(); loadSettings();
