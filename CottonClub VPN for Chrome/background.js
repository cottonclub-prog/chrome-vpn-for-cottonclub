/* All connection control lives here, never in a website/content script. */
const HOST = 'com.cottonclub.hysteria2';
const PORT = 17892;
let native = null;
let nextId = 1;
const pending = new Map();
let serial = Promise.resolve();
let state = {mode: 'off', busy: false, nodes: [], selected: 0, ip: '', message: '', helper: false, routingMode: 'ru-direct'};
let desired = false;
let savedNode = null;
state.currentVersion = chrome.runtime.getManifest().version;
state.enterprise = Boolean(chrome.runtime.getManifest().update_url);
state.update = null;
state.updating = false;
state.updateReady = false;
state.updateFailed = false;
state.routingRules = [];
let updateRequest = null;

function restoreSelection() {
  const match = state.nodes.find(node => node.name === savedNode?.name && node.protocol === savedNode?.protocol);
  state.selected = match ? match.index : (state.nodes[0]?.index || 0);
}

async function saveSelection(index) {
  const node = state.nodes.find(node => node.index === index);
  if (!node) throw new Error('Выберите подключение.');
  savedNode = {name: node.name, protocol: node.protocol};
  await chrome.storage.local.set({selectedNode: savedNode});
  state.selected = index;
}

const ready = (async () => {
  // Chrome 138 exposes setAccessLevel only on session storage.
  // Restrict local storage when supported without blocking older browsers.
  if (typeof chrome.storage.local.setAccessLevel === 'function') {
    await chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
  }
  const saved = await chrome.storage.local.get(['vpnEnabled', 'routingMode', 'routingRules', 'subscription', 'selectedNode']);
  if (Array.isArray(saved.routingRules)) state.routingRules = saved.routingRules;
  else {
    const defaults = await fetch(chrome.runtime.getURL('routing-defaults.json'));
    if (!defaults.ok) throw new Error('Не удалось прочитать исходные правила маршрутизации.');
    state.routingRules = await defaults.json();
    await chrome.storage.local.set({routingRules: state.routingRules});
  }
  savedNode = saved.selectedNode || null;
  if (!saved.subscription) {
    const previous = await chrome.storage.session.get('subscription');
    if (previous.subscription) await chrome.storage.local.set({subscription: previous.subscription});
  }
  state.routingMode = saved.routingMode === 'all' ? 'all' : 'ru-direct';
  desired = saved.vpnEnabled === true;
  if (desired) {
    try {
      await applyProxy();
      state.mode = 'blocked';
      state.message = 'Переподключитесь к VPN или нажмите «Отключить». Прямой доступ не включён.';
    } catch (error) {
      state.mode = 'error';
      state.message = `${error.message} VPN пока не управляет трафиком Chrome.`;
    }
  }
  await chrome.storage.session.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
  const updateProgress = await chrome.storage.session.get('updatePending');
  updateRequest = updateProgress.updatePending || null;
  state.updating = Boolean(updateRequest);
  if (state.updating) state.message = 'Проверяю результат установки…';
  await badge();
})();

async function badge() {
  const text = state.mode === 'on' ? 'ON' : ['blocked', 'error'].includes(state.mode) ? '!' : '';
  await chrome.action.setBadgeText({text});
  await chrome.action.setBadgeBackgroundColor({color: state.mode === 'on' ? '#167c5a' : '#b64c26'});
  await chrome.action.setTitle({title: `COTTONCLUB VPN · ${state.mode === 'on' ? 'Подключено' : ['blocked', 'error'].includes(state.mode) ? 'Соединение потеряно' : 'Отключено'}`});
}

function absorb(data) {
  state.helper = true;
  state.nodes = data.nodes || [];
  if (data.connected && data.selected !== null && data.selected !== undefined) state.selected = data.selected;
  state.ip = data.ip || '';
  if (data.connected && ['ru-direct', 'all'].includes(data.routingMode)) state.routingMode = data.routingMode;
}

function nativeLost(message) {
  state.helper = false;
  state.ip = '';
  if (state.updating) return;
  if (desired) {
    if (state.mode !== 'error') state.mode = 'blocked';
    state.message = message || 'Помощник остановлен. Доступ заблокирован до переподключения или отключения VPN.';
  } else {
    state.message = message || 'Установите помощник: запустите Install.cmd из комплекта расширения.';
  }
  badge().catch(() => {});
}

function openNative() {
  if (native) return native;
  const port = chrome.runtime.connectNative(HOST);
  native = port;
  port.onMessage.addListener(message => {
    if (message.event === 'stopped') {
      nativeLost(message.error);
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.ok) request.resolve(message.result);
    else request.reject(new Error(message.error || 'Ошибка помощника.'));
  });
  port.onDisconnect.addListener(() => {
    // Consume lastError, but don't expose platform-specific paths to the UI.
    const ignored = chrome.runtime.lastError;
    if (native !== port) return;
    native = null;
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error('Помощник недоступен. Запустите Install.cmd из комплекта расширения.'));
    }
    pending.clear();
    nativeLost();
  });
  return port;
}

function rpc(action, fields = {}) {
  return new Promise((resolve, reject) => {
    const port = openNative();
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('Помощник не ответил. Попробуйте ещё раз.'));
      port.disconnect();
      if (native === port) {
        native = null;
        nativeLost();
      }
    }, 65000);
    pending.set(id, {resolve, reject, timer});
    try { port.postMessage({id, action, ...fields}); }
    catch (error) { clearTimeout(timer); pending.delete(id); reject(new Error('Не удалось запустить помощник.')); }
  });
}

async function canControl(setting) {
  const result = await setting.get({incognito: false});
  if (!['controllable_by_this_extension', 'controlled_by_this_extension'].includes(result.levelOfControl)) {
    throw new Error('Настройки Chrome управляются другим расширением или администратором.');
  }
}

async function applyProxy() {
  const webRTC = chrome.privacy.network.webRTCIPHandlingPolicy;
  const prediction = chrome.privacy.network.networkPredictionEnabled;
  await canControl(chrome.proxy.settings);
  await canControl(webRTC);
  await canControl(prediction);
  await webRTC.set({value: 'disable_non_proxied_udp', scope: 'regular'});
  await prediction.set({value: false, scope: 'regular'});
  await chrome.proxy.settings.set({scope: 'regular', value: {
    mode: 'fixed_servers', rules: {
      singleProxy: {scheme: 'socks5', host: '127.0.0.1', port: PORT},
      bypassList: ['<-loopback>']
    }
  }});
  const actual = await chrome.proxy.settings.get({incognito: false});
  if (!ownsProxy(actual)) {
    throw new Error('Chrome не применил настройки прокси.');
  }
}

function ownsProxy(details) {
  return details.levelOfControl === 'controlled_by_this_extension' &&
    details.value?.mode === 'fixed_servers' &&
    details.value?.rules?.singleProxy?.host === '127.0.0.1' &&
    details.value?.rules?.singleProxy?.port === PORT;
}

async function releaseSettings() {
  // clear releases only our own preference layer, restoring earlier user settings.
  await chrome.proxy.settings.clear({scope: 'regular'});
  await chrome.privacy.network.webRTCIPHandlingPolicy.clear({scope: 'regular'});
  await chrome.privacy.network.networkPredictionEnabled.clear({scope: 'regular'});
}

async function readUpdateProgress() {
  state.updateReady = false;
  state.updateFailed = false;
  try {
    if (!updateRequest?.id) throw new Error('legacy');
    const response = await fetch(chrome.runtime.getURL('update-status.json'), {cache: 'no-store'});
    if (!response.ok) throw new Error('missing');
    const result = await response.json();
    if (result.id !== updateRequest.id) throw new Error('stale');
    if (result.phase === 'failed') {
      state.updateFailed = true;
      state.message = `Обновление не установлено: ${String(result.message || 'Ошибка установщика').slice(0, 500)}. Подробности: %LOCALAPPDATA%\\CottonClub VPN for Chrome\\update.log`;
    } else if (result.phase === 'complete') {
      const manifestResponse = await fetch(chrome.runtime.getURL('manifest.json'), {cache: 'no-store'});
      if (!manifestResponse.ok) throw new Error('manifest');
      const manifest = await manifestResponse.json();
      if (manifest.version !== result.version || manifest.version !== updateRequest.version) {
        state.updateFailed = true;
        state.message = 'Новая версия не найдена в папке этого расширения. Установите свежий комплект и загрузите папку %LOCALAPPDATA%\\CottonClub VPN for Chrome\\CottonClub VPN for Chrome в chrome://extensions.';
      } else {
        state.updateReady = true;
        state.message = `Версия ${result.version} установлена. Теперь перезагрузите расширение.`;
      }
    } else {
      state.message = Date.now() - updateRequest.started > 600000
        ? 'Обновление не подтвердило завершение. Проверьте %LOCALAPPDATA%\\CottonClub VPN for Chrome\\update.log. Для ручной установки сначала выключите расширение в chrome://extensions.'
        : 'Обновление выполняется. Кнопка перезагрузки станет доступна после проверки установленной версии.';
    }
  } catch (_) {
    state.message = 'Результат обновления пока недоступен. Если ожидание не помогает, выключите расширение и запустите Install.cmd из свежего комплекта. Загружайте расширение из %LOCALAPPDATA%\\CottonClub VPN for Chrome\\CottonClub VPN for Chrome.';
  }
}

async function execute(command, message) {
  await ready;
  state.busy = true;
  try {
    if (command === 'finishUpdate') {
      if (!state.updating) throw new Error('Обновление не запущено.');
      await readUpdateProgress();
      if (!state.updateReady && !state.updateFailed) return {...state, busy: false};
      await chrome.storage.session.remove('updatePending');
      setTimeout(() => chrome.runtime.reload(), 200);
    } else if (state.updating) {
      // Opening the popup must not restart the helper while the installer runs.
      await readUpdateProgress();
    } else if (command === 'saveRouting') {
      if (desired || state.mode === 'on') throw new Error('Сначала отключите VPN, затем сохраните правила.');
      const result = await rpc('validateRouting', {rules: message.rules});
      await chrome.storage.local.set({routingRules: result.rules});
      state.routingRules = result.rules;
      state.message = 'Правила сохранены. Они применятся при следующем подключении в режиме «По правилам».';
      return {...state, busy: false, saved: true};
    } else if (command === 'checkUpdate') {
      state.update = null;
      state.update = await rpc('checkUpdate', {version: state.currentVersion});
      state.message = state.update.available ? `Доступна версия ${state.update.version}.` : 'Установлена актуальная версия.';
    } else if (command === 'installUpdate') {
      if (state.enterprise) {
        state.message = 'CRX обновляется корпоративной политикой Chrome. Для обновления помощника используйте новый EXE-установщик из Releases.';
        return {...state, busy:false};
      }
      if (!state.update?.available) throw new Error('Сначала проверьте наличие обновления.');
      let managed = false;
      try {
        const response = await fetch(chrome.runtime.getURL('managed-install.json'), {cache: 'no-store'});
        managed = response.ok && (await response.json()).managed === true;
      } catch (_) {}
      if (!managed) throw new Error('Расширение загружено из неустановленной копии. Запустите Install.cmd и в chrome://extensions загрузите папку %LOCALAPPDATA%\\CottonClub VPN for Chrome\\CottonClub VPN for Chrome. Копия из Downloads автоматически не обновляется.');
      await releaseSettings();
      desired = false;
      await chrome.storage.local.set({vpnEnabled: false});
      state.mode = 'off';
      state.ip = '';
      await rpc('disconnect');
      // Persist before launching to survive a service-worker restart.
      await chrome.storage.session.set({updatePending: true});
      state.updating = true;
      state.updateReady = false;
      state.updateFailed = false;
      try {
        const result = await rpc('installUpdate');
        if (!result.started || !result.id) throw new Error('Установщик не подтвердил запуск. Установите свежий комплект вручную.');
        updateRequest = {id: result.id, version: state.update.version, started: Date.now()};
        await chrome.storage.session.set({updatePending: updateRequest});
      } catch (error) {
        state.updating = false;
        await chrome.storage.session.remove('updatePending');
        throw error;
      }
      const port = native;
      native = null;
      if (port) port.disconnect();
      state.helper = false;
      state.message = 'VPN отключён. Обновление выполняется; ожидаю подтверждения установленной версии.';
    } else if (command === 'refresh') {
      let result = await rpc('status');
      if (!result.connected && !result.nodes?.length) {
        const saved = await chrome.storage.local.get('subscription');
        if (saved.subscription) result = await rpc('load', {subscription: saved.subscription});
      }
      absorb(result);
      if (!result.connected) restoreSelection();
      const proxy = await chrome.proxy.settings.get({incognito: false});
      if (desired && !ownsProxy(proxy)) {
        state.mode = 'error';
        state.message = 'Прокси изменён извне. VPN не управляет трафиком Chrome.';
      } else if (desired && !result.connected) {
        state.mode = 'blocked';
        state.message = 'Переподключитесь или отключите VPN. Прямой доступ не включён.';
      } else if (desired && result.connected) {
        state.mode = 'on';
        state.message = 'Подключено';
      } else {
        state.message = state.nodes.length ? 'Конфигурация восстановлена. Выберите сервер и подключитесь.' : 'Помощник готов. Загрузите подписку.';
      }
    } else if (command === 'load') {
      if (state.mode === 'on') throw new Error('Сначала отключите VPN.');
      if (typeof message.subscription !== 'string' || message.subscription.length > 2 * 1024 * 1024) throw new Error('Некорректная ссылка.');
      const result = await rpc('load', {subscription: message.subscription.trim()});
      absorb(result);
      restoreSelection();
      await chrome.storage.local.set({subscription: message.subscription.trim()});
      await chrome.storage.session.remove('subscription');
      await saveSelection(state.selected);
      state.message = `Подключений: ${state.nodes.length}.${result.skipped ? ` Пропущено строк: ${result.skipped}.` : ''}`;
    } else if (command === 'select') {
      if (state.mode === 'on') throw new Error('Сначала отключите VPN.');
      await saveSelection(message.index);
    } else if (command === 'routing') {
      if (state.mode === 'on') throw new Error('Отключите VPN перед сменой маршрутизации.');
      if (!['ru-direct', 'all'].includes(message.mode)) throw new Error('Неизвестный режим маршрутизации.');
      state.routingMode = message.mode;
      await chrome.storage.local.set({routingMode: state.routingMode});
      state.message = state.routingMode === 'ru-direct' ? 'Будут применены ваши правила маршрутизации.' : 'Все сайты будут открываться через VPN; ваши правила временно не применяются.';
    } else if (command === 'connect') {
      if (!Number.isInteger(message.index)) throw new Error('Выберите подключение.');
      await saveSelection(message.index);
      await canControl(chrome.proxy.settings);
      state.message = 'Проверяю соединение…';
      const wasDesired = desired;
      const result = await rpc('connect', {index: message.index, routing_mode: state.routingMode, routing_rules: state.routingRules});
      absorb(result);
      try {
        // Persist intent first. After a browser crash the proxy must not silently clear.
        desired = true;
        await chrome.storage.local.set({vpnEnabled: true});
        await applyProxy();
        state.mode = 'on';
        state.message = state.routingMode === 'ru-direct' ? 'Подключено по вашим правилам. Остальное — через VPN.' : 'Подключено. Все сайты — через VPN.';
      } catch (error) {
        await rpc('disconnect').catch(() => {});
        if (!wasDesired) {
          await releaseSettings();
          desired = false;
          await chrome.storage.local.set({vpnEnabled: false});
          state.mode = 'off';
        } else {
          state.mode = 'blocked';
        }
        throw error;
      }
    } else if (command === 'disconnect') {
      // Explicit user action: restore previous browser preferences, then stop the core.
      await releaseSettings();
      desired = false;
      await chrome.storage.local.set({vpnEnabled: false});
      state.mode = 'off';
      state.ip = '';
      if (native) await rpc('disconnect').catch(() => {});
      state.message = 'Отключено. Восстановлены прежние настройки Chrome.';
    } else {
      throw new Error('Неизвестная команда.');
    }
  } catch (error) {
    if (desired && state.mode !== 'error' && command !== 'checkUpdate') state.mode = 'blocked';
    state.message = error.message || 'Ошибка подключения.';
  } finally {
    state.busy = false;
    await badge();
  }
  return {...state};
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return false;
  if (message.command === 'getState') {
    ready.then(async () => {
      if (state.updating && !state.busy) await readUpdateProgress();
      const saved = await chrome.storage.local.get('subscription');
      respond({...state, subscription: saved.subscription || ''});
    });
  } else {
    serial = serial.catch(() => {}).then(() => execute(message.command, message));
    serial.then(respond, () => respond({...state, busy: false, message: 'Ошибка помощника.'}));
  }
  return true;
});

chrome.runtime.onStartup.addListener(() => { ready.then(() => badge()); });
chrome.alarms.create('health', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== 'health' || !desired || state.busy || !native) return;
  serial = serial.catch(() => {}).then(async () => {
    try {
      const result = await rpc('status');
      if (!result.connected) nativeLost('Соединение остановлено. Переподключитесь или отключите VPN.');
    } catch (_) { nativeLost(); }
  });
});

chrome.proxy.settings.onChange.addListener(details => {
  if (desired && !state.busy && !ownsProxy(details)) {
    state.mode = 'error';
    state.message = 'Прокси изменён извне. VPN больше не управляет трафиком Chrome.';
    badge().catch(() => {});
  }
});
