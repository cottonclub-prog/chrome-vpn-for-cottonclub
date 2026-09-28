const el = id => document.getElementById(id);
let nodesSignature = '';
let initialized = false;
let pending = false;

function update(id, property, value) {
  const element = el(id);
  if (element[property] !== value) element[property] = value;
}

function render(state) {
  if (!state) return;
  if (!initialized) {
    el('subscription').value = state.subscription || '';
    initialized = true;
  }
  const signature = JSON.stringify(state.nodes);
  if (signature !== nodesSignature) {
    nodesSignature = signature;
    el('server').replaceChildren();
    for (const node of state.nodes || []) {
      const option = document.createElement('option');
      option.value = node.index;
      option.textContent = `${node.name} · ${node.protocol === 'vless' ? 'VLESS' : 'Hysteria 2'}`;
      el('server').append(option);
    }
    if (!state.nodes?.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Сначала загрузите подписку';
      el('server').append(option);
    } else el('server').value = String(state.selected || 0);
  }
  const busy = state.busy || pending;
  const on = state.mode === 'on';
  if (!pending && state.selected !== undefined) update('server', 'value', String(state.selected));
  for (const id of ['subscription', 'paste', 'load', 'server', 'routing']) update(id, 'disabled', busy || on);
  if (state.routingMode && !pending) update('routing', 'value', state.routingMode);
  update('connect', 'disabled', busy || on || !state.nodes?.length);
  update('disconnect', 'disabled', busy || state.mode === 'off');
  update('badge', 'textContent', on ? 'Подключён' : state.mode === 'blocked' ? 'Нет соединения' : state.mode === 'error' ? 'Нет защиты' : 'Отключён');
  update('badge', 'className', state.mode);
  update('status', 'textContent', state.message || 'Загрузите подписку и выберите сервер.');
  update('ip', 'textContent', on && state.ip ? `IP VPN: ${state.ip}` : '');
}

async function command(command, fields = {}) {
  pending = true;
  for (const id of ['connect', 'disconnect', 'load', 'paste']) el(id).disabled = true;
  try {
    const state = await chrome.runtime.sendMessage({command, ...fields});
    pending = false;
    render(state);
  } catch (_) {
    pending = false;
    el('status').textContent = 'Расширение перезапущено. Закройте и откройте это окно.';
  }
}

el('show').addEventListener('change', () => { el('subscription').type = el('show').checked ? 'text' : 'password'; });
el('paste').addEventListener('click', async () => {
  try { el('subscription').value = (await navigator.clipboard.readText()).trim(); }
  catch (_) { el('status').textContent = 'Вставьте ссылку в поле сочетанием Ctrl+V.'; }
});
el('load').addEventListener('click', () => command('load', {subscription: el('subscription').value}));
el('subscription').addEventListener('keydown', event => { if (event.key === 'Enter') el('load').click(); });
el('connect').addEventListener('click', () => command('connect', {index: Number(el('server').value)}));
el('disconnect').addEventListener('click', () => command('disconnect'));
el('routing').addEventListener('change', () => command('routing', {mode: el('routing').value}));
el('server').addEventListener('change', () => command('select', {index: Number(el('server').value)}));
chrome.runtime.sendMessage({command: 'getState'}).then(render).then(() => command('refresh'));
setInterval(() => chrome.runtime.sendMessage({command: 'getState'}).then(render).catch(() => {}), 750);
