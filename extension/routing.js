const byId = id => document.getElementById(id);
let rules = [];
let dirty = false;
let saving = false;
let loaded = false;

function changed() {
  dirty = true;
  byId('save-status').textContent = 'Есть несохранённые изменения.';
}
function select(options, value, title, change) {
  const control = document.createElement('select');
  control.setAttribute('aria-label', title);
  for (const [key, text] of options) {
    const option = document.createElement('option');
    option.value = key; option.textContent = text; control.append(option);
  }
  control.value = value;
  control.addEventListener('change', () => { change(control.value); changed(); });
  return control;
}
function label(text, control, className = '') {
  const element = document.createElement('label');
  element.textContent = text; element.className = className; element.append(control);
  return element;
}
function render() {
  byId('rules').replaceChildren();
  byId('empty').hidden = rules.length !== 0;
  rules.forEach((rule, index) => {
    const row = document.createElement('div'); row.className = 'rule';
    const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = rule.enabled;
    enabled.setAttribute('aria-label', `Правило ${index + 1}: включено`);
    enabled.addEventListener('change', () => { rule.enabled = enabled.checked; changed(); });
    row.append(enabled);
    row.append(label('Тип', select([['domain', 'Домен'], ['ip', 'IP / подсеть'], ['geoip-ru', 'IP России']], rule.type, 'Тип правила', value => {
      rule.type = value; rule.value = ''; render();
    })));
    const value = document.createElement('input');
    value.type = 'text'; value.spellcheck = false; value.maxLength = 253;
    value.value = rule.type === 'geoip-ru' ? 'Russia' : rule.value === 'xn--p1ai' ? '.рф' : ['ru', 'su'].includes(rule.value) ? '.' + rule.value : rule.value;
    value.disabled = rule.type === 'geoip-ru';
    value.placeholder = rule.type === 'ip' ? '192.168.0.0/16' : 'example.com или .ru';
    value.addEventListener('input', () => { rule.value = value.value; changed(); });
    row.append(label('Домен или адрес', value, 'destination'));
    row.append(label('Маршрут', select([['direct', 'Напрямую'], ['vpn', 'Через VPN']], rule.outbound, 'Маршрут', next => { rule.outbound = next; })));
    const actions = document.createElement('div'); actions.className = 'actions';
    for (const [text, title, action, disabled] of [
      ['↑', 'Выше', () => { [rules[index - 1], rules[index]] = [rules[index], rules[index - 1]]; }, index === 0],
      ['↓', 'Ниже', () => { [rules[index + 1], rules[index]] = [rules[index], rules[index + 1]]; }, index === rules.length - 1],
      ['×', 'Удалить', () => rules.splice(index, 1), false],
    ]) {
      const button = document.createElement('button'); button.className = 'secondary'; button.textContent = text;
      button.setAttribute('aria-label', `${title}: правило ${index + 1}`); button.disabled = disabled;
      button.addEventListener('click', () => { action(); changed(); render(); }); actions.append(button);
    }
    row.append(actions); byId('rules').append(row);
  });
}
async function defaults() {
  const response = await fetch('routing-defaults.json');
  if (!response.ok) throw new Error('Не удалось прочитать исходные правила.');
  return response.json();
}
byId('add-rule').addEventListener('click', () => {
  if (!loaded || saving) return;
  if (rules.length >= 500) { byId('save-status').textContent = 'Максимум 500 правил.'; return; }
  rules.push({type: 'domain', value: '', outbound: 'direct', enabled: true}); changed(); render();
});
byId('reset-rules').addEventListener('click', async () => {
  if (!loaded || saving || !confirm('Заменить список четырьмя исходными правилами? Изменения вступят в силу после сохранения.')) return;
  try { rules = await defaults(); changed(); render(); } catch (error) { byId('save-status').textContent = error.message; }
});
byId('save-rules').addEventListener('click', async () => {
  if (!loaded || saving) return;
  saving = true;
  for (const control of document.querySelectorAll('button,input,select')) control.disabled = true;
  try {
    const result = await chrome.runtime.sendMessage({command: 'saveRouting', rules});
    if (result.saved) { rules = result.routingRules; dirty = false; }
    byId('save-status').textContent = result.message || 'Не удалось сохранить правила.';
  } catch (_) { byId('save-status').textContent = 'Расширение недоступно. Откройте настройки повторно.'; }
  finally {
    saving = false; render();
    for (const id of ['save-rules', 'add-rule', 'reset-rules']) byId(id).disabled = false;
  }
});
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
chrome.runtime.sendMessage({command: 'getState'}).then(state => {
  rules = structuredClone(state.routingRules); loaded = true; render();
  byId('save-status').textContent = state.mode === 'on' ? 'Отключите VPN перед сохранением.' : 'Измените правила и нажмите «Сохранить».';
}).catch(() => { byId('save-status').textContent = 'Не удалось загрузить настройки. Откройте страницу повторно.'; });
