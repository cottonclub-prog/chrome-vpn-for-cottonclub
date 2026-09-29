
const $=id=>document.getElementById(id);let rules=[],editing=-1,connected=false,timer;const icon=name=>{const s=document.createElementNS('http://www.w3.org/2000/svg','svg'),u=document.createElementNS(s.namespaceURI,'use');u.setAttribute('href','#'+name);s.append(u);return s};
let currentState = {}, pending = false, initialized = false, rulesLoaded = false, rulesDirty = false, nodesSignature = '';
function displayRuleValue(value) { return value === 'xn--p1ai' ? '.рф' : ['ru','su'].includes(value) ? '.' + value : value; }
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(timer);timer=setTimeout(()=>$('toast').hidden=true,3200)}
function screen(name){document.querySelectorAll('.screen').forEach(s=>s.hidden=s.id!==name);document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected',String(t.dataset.screen===name)));document.querySelector('.body').scrollTop=0}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>screen(t.dataset.screen));$('open-rules').onclick=()=>screen('rules');
function render(){const list=$('rule-list');list.replaceChildren();rules.forEach((r,i)=>{const row=document.createElement('div');row.className='rule'+(r.enabled?'':' off');const badge=document.createElement('span');badge.className='rule-icon';badge.append(icon(r.type==='ip'?'route':'globe'));const content=document.createElement('div');content.className='grow';const name=document.createElement('div');name.className='rule-name';name.title=r.value;name.textContent=r.type==='geoip-ru'?'IP России':displayRuleValue(r.value);const type=document.createElement('div');type.className='rule-type';type.textContent=(i+1)+'. '+(r.type==='geoip-ru'?'Группа адресов':r.type==='ip'?'IP / подсеть':'Домен и поддомены');content.append(name,type);const route=document.createElement('button');route.className='route-badge'+(r.outbound==='vpn'?' vpn':'');route.textContent=r.outbound==='vpn'?'Через VPN':'Напрямую';route.title='Изменить маршрут';route.onclick=()=>{r.outbound=r.outbound==='vpn'?'direct':'vpn';render();dirty()};const edit=document.createElement('button');edit.className='iconbtn';edit.setAttribute('aria-label','Изменить '+name.textContent);edit.append(icon('edit'));edit.onclick=()=>openEditor(i);row.append(badge,content,route,edit);list.append(row)});if(!rules.length){const p=document.createElement('div');p.className='empty';p.textContent='Правил пока нет. Всё идёт через VPN.';list.append(p)}}
function syncEditorRoute(){document.querySelectorAll('[data-direction]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.direction===$('rule-outbound').value)))}
document.querySelectorAll('[data-direction]').forEach(b=>b.onclick=()=>{$('rule-outbound').value=b.dataset.direction;syncEditorRoute()});
function syncLinkVisibility(){const visible=$('subscription').type==='text';$('show-sub').replaceChildren(icon(visible?'eye-off':'eye'));$('show-sub').setAttribute('aria-label',visible?'Скрыть ссылку':'Показать ссылку');$('show-sub').title=visible?'Скрыть ссылку':'Показать ссылку';$('show-sub').setAttribute('aria-pressed',String(visible))}
syncLinkVisibility();

const addressOptions=[...document.querySelectorAll('.address-option')];
function syncAddressType(){const current=addressOptions.find(o=>o.dataset.type===$('rule-type').value);$('address-caption').textContent=current.querySelector('strong').textContent;$('address-trigger').querySelector('use').setAttribute('href',current.querySelector('use').getAttribute('href'));addressOptions.forEach(o=>o.setAttribute('aria-selected',String(o===current)))}
function closeAddressList(focus=false){$('address-options').hidden=true;$('address-trigger').setAttribute('aria-expanded','false');if(focus)$('address-trigger').focus()}
function openAddressList(){$('address-options').hidden=false;$('address-trigger').setAttribute('aria-expanded','true');addressOptions.find(o=>o.dataset.type===$('rule-type').value).focus()}
$('address-trigger').onclick=()=>{$('address-options').hidden?openAddressList():closeAddressList(true)};
$('address-trigger').onkeydown=e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();openAddressList();if(e.key==='Home')addressOptions[0].focus();if(e.key==='End')addressOptions.at(-1).focus()}};
addressOptions.forEach(o=>o.onclick=()=>{$('rule-type').value=o.dataset.type;typeChanged();closeAddressList(true)});
$('address-picker').addEventListener('keydown',e=>{if($('address-options').hidden)return;const index=addressOptions.indexOf(document.activeElement);if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeAddressList(true)}else if(e.key==='Tab'){closeAddressList(true)}else if(index>=0){if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?addressOptions.length-1:(index+(e.key==='ArrowDown'?1:-1)+addressOptions.length)%addressOptions.length;addressOptions[next].focus()}else if(e.key==='Enter'||e.key===' '){e.preventDefault();addressOptions[index].click()}}});
document.addEventListener('pointerdown',e=>{if(!$('address-picker').contains(e.target))closeAddressList()});
syncAddressType();

function dirty(){rulesDirty=true;$('rule-note').textContent='Есть несохранённые изменения.'}
function typeChanged(){syncAddressType();$('rule-value').disabled=$('rule-type').value==='geoip-ru';$('rule-value').required=!$('rule-value').disabled;$('rule-value').placeholder=$('rule-type').value==='ip'?'192.168.0.0/16':'example.com';if($('rule-value').disabled)$('rule-value').value='Russia';else if($('rule-value').value==='Russia')$('rule-value').value='';$('rule-value-help').textContent=$('rule-type').value==='geoip-ru'?'Встроенная группа публичных IP-адресов России.':$('rule-type').value==='ip'?'IPv4, IPv6 или подсеть: например, 192.168.0.0/16.':'Без https:// и пути. Поддомены тоже учитываются.'}
function openEditor(i){if(!rulesLoaded||pending||currentState.updating)return;if(i<0&&rules.length>=500){toast("Maximum 500 rules");return;}closeAddressList();editing=i;const r=rules[i]||{type:'domain',value:'',outbound:'direct',enabled:true};$('editor-title').textContent=i<0?'Новое правило':'Изменить правило';$('rule-type').value=r.type;$('rule-value').value=displayRuleValue(r.value);$('rule-outbound').value=r.outbound;syncEditorRoute();$('rule-enabled').checked=r.enabled;$('order-controls').hidden=i<0;$('move-up').disabled=i<=0;$('move-down').disabled=i===rules.length-1;$('editor').hidden=false;typeChanged();($('rule-value').disabled?$('address-trigger'):$('rule-value')).focus()}
function closeEditor(){closeAddressList();$('editor').hidden=true;$('add-rule').focus()}
$('add-rule').onclick=()=>openEditor(-1);$('close-editor').onclick=closeEditor;$('rule-type').onchange=typeChanged;$('rule-form').onsubmit=e=>{e.preventDefault();const value=$('rule-value').value.trim();if(!value){toast('Введите домен или IP-адрес.');return}const r={type:$('rule-type').value,value,outbound:$('rule-outbound').value,enabled:$('rule-enabled').checked};if(editing<0)rules.push(r);else rules[editing]=r;render();dirty();closeEditor()};
function move(delta){const next=editing+delta;if(next<0||next>=rules.length)return;[rules[next],rules[editing]]=[rules[editing],rules[next]];editing=next;render();dirty();openEditor(editing)}$('move-up').onclick=()=>move(-1);$('move-down').onclick=()=>move(1);$('delete-rule').onclick=()=>{rules.splice(editing,1);render();dirty();closeEditor()};

// All VPN actions use the existing worker/native-host protocol.
function countryCode(name) {
  const flag = String(name).match(/[\u{1F1E6}-\u{1F1FF}]{2}/u);
  if (flag) return [...flag[0]].map(c => String.fromCharCode(c.codePointAt(0) - 0x1F1E6 + 65)).join('');
  const match = String(name).match(/(?:^|[\s|/()[\]·-])(NL|DE|FI)(?=$|[\s|/()[\]·-])/i);
  if (match) return match[1].toUpperCase();
  if (/германи|germany|frankfurt/i.test(name)) return 'DE';
  if (/нидерланд|netherlands|amsterdam/i.test(name)) return 'NL';
  if (/финлянд|finland|helsinki/i.test(name)) return 'FI';
  return null;
}
function setFlag(element, name) {
  const code = countryCode(name);
  delete element.dataset.country;
  element.replaceChildren();
  if (['NL','DE','FI'].includes(code)) element.dataset.country = code;
  else if (code) element.textContent = [...code].map(c => String.fromCodePoint(c.charCodeAt(0) + 0x1F1E6 - 65)).join('');
  else element.append(icon('globe'));
  element.setAttribute('aria-hidden', 'true');
}
function closeServers() { $('servers').hidden = true; $('server-picker').focus(); }
function renderServers(state) {
  const signature = JSON.stringify([state.nodes, state.selected]);
  if (signature === nodesSignature) return;
  nodesSignature = signature;
  $('server-list').replaceChildren();
  for (const node of state.nodes || []) {
    const button = document.createElement('button');
    button.className = 'location-option';
    button.setAttribute('aria-pressed', String(node.index === state.selected));
    const flag = document.createElement('span'); flag.className = 'flag'; setFlag(flag, node.name);
    const text = document.createElement('span'); text.className = 'location-copy';
    const name = document.createElement('span'); name.className = 'location-name'; name.textContent = node.name; name.title = node.name;
    const protocol = document.createElement('span'); protocol.className = 'location-city'; protocol.textContent = 'Hysteria 2';
    text.append(name, protocol);
    const choice = document.createElement('span'); choice.className = 'location-check'; choice.setAttribute('aria-hidden','true');
    const check = icon('shield'); check.replaceChildren(); check.setAttribute('viewBox','0 0 24 24');
    const path = document.createElementNS(check.namespaceURI, 'path'); path.setAttribute('d','m5 12 4 4L19 6'); check.append(path); choice.append(check);
    button.append(flag,text,choice);
    button.onclick = async () => { await command('select', {index:node.index}); closeServers(); };
    $('server-list').append(button);
  }
  $('server-count').textContent = `Серверов: ${state.nodes?.length || 0}`;
  const selected = state.nodes?.find(node => node.index === state.selected);
  $('server-name').textContent = selected?.name || 'Добавьте подписку';
  $('server-name').title = selected?.name || '';
  setFlag(document.querySelector('#server-picker .flag'), selected?.name || '');
}
function renderState(state) {
  if (!state) return;
  currentState = state;
  if (!initialized) {
    $('subscription').value = state.subscription || '';
    initialized = true;
  }
  if (!rulesDirty && $('editor').hidden && Array.isArray(state.routingRules)) {
    if (!rulesLoaded || JSON.stringify(rules) !== JSON.stringify(state.routingRules)) {
      rules = structuredClone(state.routingRules); render();
    }
    rulesLoaded = true;
  }
  connected = state.mode === 'on';
  const blocked = state.mode === 'blocked' || state.mode === 'error';
  const busy = pending || state.busy || state.updating;
  $('app').classList.toggle('connected', connected);
  $('connection-status').className = 'status' + (connected ? ' on' : blocked ? ' ' + state.mode : '');
  $('status-text').textContent = busy ? (state.updating ? 'Обновление приложения' : 'Подождите…') : connected ? 'Подключено' : blocked ? 'Нет соединения' : 'Готов к подключению';
  $('hero-title').textContent = connected ? 'Ваш маршрут защищён' : blocked ? 'Соединение прервано' : 'Интернет по вашим правилам';
  $('hero-sub').textContent = connected ? (state.ip ? `IP VPN: ${state.ip}` : 'Hysteria 2 · sing-box') : blocked ? 'Нажмите кнопку, чтобы отключить VPN' : 'Нажмите, чтобы подключиться';
  $('power').setAttribute('aria-pressed',String(connected || blocked));
  $('power').setAttribute('aria-label',connected || blocked ? 'Отключить VPN' : 'Подключить VPN');
  $('power').disabled = !!busy || (!connected && !blocked && !state.nodes?.length);
  for (const id of ['subscription','load-sub','server-picker']) $(id).disabled = !!busy || connected;
  document.querySelectorAll('[data-mode]').forEach(button => {
    button.disabled = !!busy || connected;
    button.classList.toggle('active', (button.dataset.mode === 'all' ? 'all' : 'ru-direct') === state.routingMode);
  });
  for (const id of ['save-rules','add-rule','reset-rules']) $(id).disabled = !!busy || !rulesLoaded || (id === 'save-rules' && connected);
  $('status').textContent = state.message || '';
  $('status').hidden = !state.message;
  $('version').textContent = state.update?.available ? `Доступна ${state.update.version}` : `Версия ${state.currentVersion || chrome.runtime.getManifest().version}`;
  document.querySelectorAll('.app-version').forEach(e => e.textContent = state.currentVersion || chrome.runtime.getManifest().version);
  $('check-update').disabled = !!busy;
  $('install-update').hidden = !state.update?.available || !!state.updating;
  $('install-update').disabled = !!busy;
  $('finish-update').hidden = !state.updating;
  $('finish-update').textContent = state.updateFailed ? 'Вернуться к расширению' : 'Перезагрузить расширение';
  $('finish-update').disabled = !!(state.busy || pending || (!state.updateReady && !state.updateFailed));
  renderServers(state);
}
async function command(action, fields = {}) {
  if (pending) return null;
  pending = true; renderState(currentState);
  try {
    const state = await chrome.runtime.sendMessage({command:action, ...fields});
    pending = false; renderState(state); return state;
  } catch (_) {
    pending = false; renderState(currentState);
    $('status').hidden = false;
    $('status').textContent = 'Помощник недоступен или расширение перезапущено. Закройте и откройте это окно.';
    return null;
  }
}
$('power').onclick = () => command(['on','blocked','error'].includes(currentState.mode) ? 'disconnect' : 'connect', {index:currentState.selected});
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => command('routing', {mode:b.dataset.mode === 'all' ? 'all' : 'ru-direct'}));
$('server-picker').onclick = () => {
  if (!currentState.nodes?.length) { screen('settings'); $('subscription').focus(); return; }
  $('servers').hidden = false;
  ($('server-list').querySelector('[aria-pressed=true]') || $('close-servers')).focus();
};
$('close-servers').onclick = closeServers;
$('servers').onclick = e => { if(e.target === $('servers')) closeServers(); };
$('show-sub').onclick = () => { $('subscription').type = $('subscription').type === 'password' ? 'text' : 'password'; syncLinkVisibility(); };
$('load-sub').onclick = () => command('load', {subscription:$('subscription').value});
$('subscription').onkeydown = e => { if (e.key === 'Enter' && !$('load-sub').disabled) $('load-sub').click(); };
$('save-rules').onclick = async () => {
  if (!rulesLoaded || pending || connected) return;
  const snapshot = structuredClone(rules);
  const result = await command('saveRouting', {rules:snapshot});
  if (result?.saved && JSON.stringify(rules) === JSON.stringify(snapshot)) {
    rules = structuredClone(result.routingRules); rulesDirty = false; render();
  }
  $('rule-note').textContent = result?.saved ? 'Сохранено. Применится при следующем подключении.' : result?.message || 'Не удалось сохранить правила.';
};
$('reset-rules').onclick = async () => {
  if (!confirm('Заменить список четырьмя исходными правилами? После этого нажмите «Сохранить правила».')) return;
  try {
    const response = await fetch('routing-defaults.json');
    if (!response.ok) throw new Error();
    rules = await response.json(); render(); dirty(); screen('rules');
  } catch (_) { toast('Не удалось прочитать исходные правила.'); }
};
$('check-update').onclick = () => command('checkUpdate');
$('install-update').textContent = 'Обновить — VPN отключится';
$('install-update').onclick = () => command('installUpdate');
$('finish-update').onclick = () => command('finishUpdate');
$('help-link').textContent = 'Установка и помощь';
document.addEventListener('keydown', e => {
  const modal = !$('servers').hidden ? $('servers') : !$('editor').hidden ? $('editor') : null;
  if (!modal) return;
  if (e.key === 'Escape') { e.preventDefault(); modal === $('servers') ? closeServers() : closeEditor(); }
  if (e.key === 'Tab') {
    const controls = [...modal.querySelectorAll('button,input:not([type=hidden])')].filter(c => !c.disabled && c.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
render();
chrome.runtime.sendMessage({command:'getState'}).then(state => { renderState(state); return command('refresh'); }).catch(() => {
  $('status').textContent = 'Не удалось загрузить состояние расширения. Откройте окно повторно.';
});
setInterval(() => { if (!pending) chrome.runtime.sendMessage({command:'getState'}).then(state => { if (!pending) renderState(state); }).catch(() => {}); },750);
