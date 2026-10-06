const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = name => fs.readFileSync(path.join(__dirname, '../CottonClub VPN for Chrome', name), 'utf8');

function background(saved = {}, savedSession = {}, {localAccessLevel = true, enterprise = false} = {}) {
  const listeners = {};
  const storage = {...saved};
  const accessCalls = [];
  const setting = () => ({
    value: {}, levelOfControl: 'controllable_by_this_extension',
    async get() { return {value: this.value, levelOfControl: this.levelOfControl}; },
    async set({value}) { this.value = value; this.levelOfControl = 'controlled_by_this_extension'; },
    async clear() { this.value = {}; this.levelOfControl = 'controllable_by_this_extension'; },
    onChange: {addListener(fn) { this.listener = fn; }},
  });
  const chrome = {
    storage: {
      local: {async setAccessLevel(options) { accessCalls.push({area:'local', level:options.accessLevel}); }, async get() { return {...storage}; }, async set(value) { Object.assign(storage, value); }},
      session: {async setAccessLevel(options) { accessCalls.push({area:'session', level:options.accessLevel}); }, async get() { return {...savedSession}; }, async set(value) { Object.assign(savedSession, value); }, async remove(key) { delete savedSession[key]; }},
    },
    action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}, async setTitle() {}},
    proxy: {settings: setting()},
    privacy: {network: {webRTCIPHandlingPolicy: setting(), networkPredictionEnabled: setting()}},
    alarms: {create() {}, onAlarm: {addListener(fn) { listeners.alarm = fn; }}},
    runtime: {id: 'test', getManifest: () => ({version: '1.0.3', update_url:enterprise ? 'https://example.com/updates.xml' : undefined}), getURL: () => 'chrome-extension://test/',
      onMessage: {addListener(fn) { listeners.message = fn; }}, onStartup: {addListener() {}},
      connectNative() { throw new Error('Helper unavailable'); }},
  };
  if (!localAccessLevel) delete chrome.storage.local.setAccessLevel;
  const context = vm.createContext({chrome, setTimeout, clearTimeout,
    fetch: async () => ({ok: true, json: async () => JSON.parse(source('routing-defaults.json'))})});
  vm.runInContext(source('background.js'), context);
  return {chrome, storage, context, accessCalls, listeners,
    ready: vm.runInContext('ready', context),
    send(message) { return new Promise(resolve => listeners.message(message,
      {id: 'test', url: 'chrome-extension://test/popup.html'}, resolve)); },
  };
}

test('Chrome 138 without local.setAccessLevel restores saved settings and retains session restrictions', async () => {
  const rules = [{type:'domain', value:'example.com', outbound:'vpn', enabled:true}];
  const app = background({subscription:'https://example.com/sub', routingMode:'all', routingRules:rules}, {}, {localAccessLevel:false});
  await app.ready;
  const state = await app.send({command:'getState'});
  assert.equal(state.subscription, 'https://example.com/sub');
  assert.equal(state.routingMode, 'all');
  assert.deepEqual(JSON.parse(JSON.stringify(state.routingRules)), rules);
  assert.deepEqual(app.accessCalls, [{area:'session', level:'TRUSTED_CONTEXTS'}]);
});

test('Chrome 138 without local.setAccessLevel keeps enabled VPN blocked until explicit disconnect', async () => {
  const app = background({vpnEnabled:true}, {}, {localAccessLevel:false});
  await app.ready;
  assert.equal((await app.send({command:'getState'})).mode, 'blocked');
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0);
  assert.equal((await app.send({command:'disconnect'})).mode, 'off');
  assert.equal(app.storage.vpnEnabled, false);
});

test('browsers supporting local.setAccessLevel restrict both storage areas', async () => {
  const app = background();
  await app.ready;
  assert.deepEqual(app.accessCalls, [
    {area:'local', level:'TRUSTED_CONTEXTS'},
    {area:'session', level:'TRUSTED_CONTEXTS'},
  ]);
});

test('enterprise CRX never updates a separate unpacked extension or disconnects VPN', async () => {
  const app = background({}, {}, {enterprise:true});
  await app.ready;
  vm.runInContext("desired = true; state.mode = 'on'; state.update = {available:true, version:'1.5.0'}; rpc = async () => { throw new Error('Must not launch updater'); };", app.context);
  const result = await app.send({command:'installUpdate'});
  assert.equal(result.enterprise, true);
  assert.equal(result.mode, 'on');
  assert.equal(result.updating, false);
  assert.match(result.message, /CRX/);
});

test('restart with enabled VPN retains a blocking proxy until explicit disconnect', async () => {
  const app = background({vpnEnabled: true});
  await app.ready;
  assert.equal((await app.send({command: 'getState'})).mode, 'blocked');
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0);
  assert.equal((await app.send({command: 'disconnect'})).mode, 'off');
  assert.equal(app.storage.vpnEnabled, false);
  assert.equal(app.chrome.proxy.settings.levelOfControl, 'controllable_by_this_extension');
});

test('update check failure does not mark a working VPN as blocked', async () => {
  const app = background();
  await app.ready;
  vm.runInContext("desired = true; state.mode = 'on'; rpc = async () => { throw new Error('GitHub unavailable'); };", app.context);
  const result = await app.send({command: 'checkUpdate'});
  assert.equal(result.mode, 'on');
  assert.equal(result.update, null);
});

test('updater disconnects VPN, persists pending state and releases native port', async () => {
  const savedSession = {};
  const app = background({}, savedSession);
  await app.ready;
  app.context.calls = [];
  app.context.fetch = async () => ({ok: true, json: async () => ({managed: true})});
  vm.runInContext(`
    desired = true; state.mode = 'on'; state.update = {available: true, version: '1.0.4'};
    rpc = async action => { calls.push(action); return action === 'installUpdate' ? {started: true, id: 'test-update'} : {}; };
    native = {disconnect() { calls.push('nativeClosed'); }};
  `, app.context);
  const result = await app.send({command: 'installUpdate'});
  assert.equal(result.mode, 'off');
  assert.equal(result.updating, true);
  assert.equal(app.storage.vpnEnabled, false);
  assert.equal(savedSession.updatePending.id, 'test-update');
  assert.equal(savedSession.updatePending.version, '1.0.4');
  assert.deepEqual([...app.context.calls], ['disconnect', 'installUpdate', 'nativeClosed']);
  await app.send({command: 'refresh'});
  assert.equal(app.context.calls.length, 3, 'popup must not reopen the helper');
});

test('pending update survives worker restart without starting helper', async () => {
  const app = background({}, {updatePending: true});
  await app.ready;
  const state = await app.send({command: 'refresh'});
  assert.equal(state.updating, true);
  assert.equal(state.helper, false);
});

test('extension loaded from a download folder cannot start an update of another copy', async () => {
  const app = background();
  await app.ready;
  app.context.fetch = async () => ({ok: false});
  app.context.calls = [];
  vm.runInContext("state.update = {available: true, version: '1.0.4'}; rpc = async action => { calls.push(action); };", app.context);
  const state = await app.send({command: 'installUpdate'});
  assert.equal(state.updating, false);
  assert.equal(app.context.calls.length, 0);
  assert.match(state.message, /Downloads/);
});

test('reload is blocked until installation completes, including after a worker restart', async () => {
  const savedSession = {updatePending: {id: 'request', version: '1.0.4', started: Date.now()}};
  const app = background({}, savedSession);
  await app.ready;
  let phase = 'installing';
  let manifestVersion = '1.0.3';
  app.chrome.runtime.getURL = name => name;
  app.context.fetch = async url => ({ok: true, json: async () => url === 'manifest.json'
    ? {version: manifestVersion} : {id: 'request', phase, version: '1.0.4'}});
  let reloads = 0;
  app.chrome.runtime.reload = () => reloads++;
  app.context.setTimeout = fn => fn();
  let state = await app.send({command: 'finishUpdate'});
  assert.equal(state.updateReady, false);
  assert.equal(reloads, 0);
  assert.ok(savedSession.updatePending);
  phase = 'complete';
  manifestVersion = '1.0.4';
  state = await app.send({command: 'finishUpdate'});
  assert.equal(state.updateReady, true);
  assert.equal(reloads, 1);
  assert.equal(savedSession.updatePending, undefined);
});

test('failed installer and wrong extension folder are not reported as successful updates', async () => {
  const app = background({}, {updatePending: {id: 'request', version: '1.0.4', started: Date.now()}});
  await app.ready;
  app.chrome.runtime.getURL = name => name;
  let phase = 'failed';
  app.context.fetch = async url => ({ok: true, json: async () => url === 'manifest.json'
    ? {version: '1.0.3'} : {id: 'request', phase, version: '1.0.4', message: 'Download failed'}});
  let state = await app.send({command: 'getState'});
  assert.equal(state.updateReady, false);
  assert.equal(state.updateFailed, true);
  assert.match(state.message, /Download failed/);
  phase = 'complete';
  state = await app.send({command: 'getState'});
  assert.equal(state.updateReady, false);
  assert.equal(state.updateFailed, true);
  assert.match(state.message, /chrome:\/\/extensions/);
});

test('stale completion from a previous update cannot enable reload', async () => {
  const app = background({}, {updatePending: {id: 'request', version: '1.0.4', started: Date.now()}});
  await app.ready;
  app.context.fetch = async () => ({ok: true, json: async () => ({id: 'previous', phase: 'complete', version: '1.0.4'})});
  const state = await app.send({command: 'finishUpdate'});
  assert.equal(state.updateReady, false);
  assert.equal(state.updateFailed, false);
});

test('a failed badge update does not permanently break the command queue', async () => {
  const app = background();
  await app.ready;
  const original = app.chrome.action.setBadgeText;
  app.chrome.action.setBadgeText = async () => { throw new Error('Transient API failure'); };
  await app.send({command: 'routing', mode: 'all'});
  app.chrome.action.setBadgeText = original;
  const result = await app.send({command: 'routing', mode: 'ru-direct'});
  assert.equal(result.routingMode, 'ru-direct');
  assert.equal(app.storage.routingMode, 'ru-direct');
});

test('unavailable helper leaves disabled VPN off', async () => {
  const app = background();
  await app.ready;
  const result = await app.send({command: 'refresh'});
  assert.equal(result.mode, 'off');
  assert.equal(result.busy, false);
});

test('routing defaults migrate once and an explicitly empty list survives restart', async () => {
  const app = background();
  await app.ready;
  assert.equal(app.storage.routingRules.length, 4);
  const empty = background({routingRules: []});
  await empty.ready;
  assert.deepEqual([...empty.storage.routingRules], []);
});

test('rules are validated before saving and restored after worker restart', async () => {
  const app = background();
  await app.ready;
  const rules = [{type: 'domain', value: 'example.com', outbound: 'vpn', enabled: true}];
  app.context.rules = rules;
  vm.runInContext('rpc = async (action, fields) => { if (action !== "validateRouting") throw new Error("Unexpected action"); return {rules: fields.rules}; };', app.context);
  const saved = await app.send({command: 'saveRouting', rules});
  assert.equal(saved.saved, true);
  assert.deepEqual(app.storage.routingRules, rules);
  const restarted = background(app.storage);
  await restarted.ready;
  assert.deepEqual((await restarted.send({command: 'getState'})).routingRules, rules);
  vm.runInContext('rpc = async () => { throw new Error("Invalid rule"); };', app.context);
  const rejected = await app.send({command: 'saveRouting', rules: []});
  assert.equal(rejected.saved, undefined);
  assert.deepEqual(app.storage.routingRules, rules);
});

test('saving rules while VPN is active is rejected without changing storage', async () => {
  const app = background({vpnEnabled: true});
  await app.ready;
  const result = await app.send({command: 'saveRouting', rules: []});
  assert.equal(result.saved, undefined);
  assert.equal(app.storage.routingRules.length, 4);
});

// Popup selection regression is covered in routing_ui_smoke.py with a real DOM.

function helper(app, assignedPort = 24567) {
  const state = {connected:false, port:assignedPort, nodes:[{index:0, name:'Test', protocol:'hysteria2'}]};
  const events = {};
  const native = {
    onMessage: {addListener(fn) { events.message = fn; }},
    onDisconnect: {addListener(fn) { events.disconnect = fn; }},
    disconnect() { state.connected = false; events.disconnect(); },
    postMessage(message) {
      if (message.action === 'connect') {
        assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0, 'old/free ports must not be used while the core starts');
        state.connected = true;
      }
      if (message.action === 'disconnect') state.connected = false;
      events.message({id:message.id, ok:true, result:{...state, selected:0}});
    },
  };
  app.chrome.runtime.connectNative = () => native;
  return {state, native, events};
}

test('independent profiles use the port advertised by their own helper', async () => {
  const first = background(), second = background();
  await Promise.all([first.ready, second.ready]);
  helper(first, 24567); helper(second, 25678);
  for (const app of [first, second]) {
    await app.send({command:'refresh'});
    assert.equal((await app.send({command:'connect', index:0})).mode, 'on');
  }
  assert.equal(first.chrome.proxy.settings.value.rules.singleProxy.port, 24567);
  assert.equal(second.chrome.proxy.settings.value.rules.singleProxy.port, 25678);
});

test('reconnect retires the previous port and uses the newly assigned port', async () => {
  const app = background(); await app.ready;
  const backend = helper(app, 24567);
  await app.send({command:'refresh'});
  await app.send({command:'connect', index:0});
  backend.state.port = 25678;
  assert.equal((await app.send({command:'connect', index:0})).mode, 'on');
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 25678);
});

test('helper disconnection replaces a reusable old port with a non-listening blocking endpoint', async () => {
  const app = background(); await app.ready;
  const backend = helper(app);
  await app.send({command:'refresh'});
  await app.send({command:'connect', index:0});
  backend.native.disconnect();
  await vm.runInContext('blocking', app.context);
  assert.equal((await app.send({command:'getState'})).mode, 'blocked');
  assert.equal(app.chrome.proxy.settings.value.mode, 'fixed_servers');
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0);
  assert.deepEqual([...app.chrome.proxy.settings.value.rules.bypassList], ['<-loopback>']);
  assert.equal(app.storage.vpnEnabled, true);
  assert.equal((await app.send({command:'disconnect'})).mode, 'off');
  assert.equal(app.chrome.proxy.settings.value.mode, undefined);
});

test('worker restart never restores a previously assigned port', async () => {
  const app = background({vpnEnabled:true});
  app.chrome.proxy.settings.value = {mode:'fixed_servers', rules:{singleProxy:{scheme:'socks5', host:'127.0.0.1', port:24567}}};
  app.chrome.proxy.settings.levelOfControl = 'controlled_by_this_extension';
  await app.ready;
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0);
});

test('missing, malformed and zero ports never activate a proxy and stop the core', async () => {
  for (const port of [undefined, 0, -1, 65536, '24567', 1.5]) {
    const app = background(); await app.ready;
    const backend = helper(app); backend.state.port = port;
    await app.send({command:'refresh'});
    const result = await app.send({command:'connect', index:0});
    assert.equal(result.mode, 'off');
    assert.match(result.message, /порт/);
    assert.equal(backend.state.connected, false);
    assert.equal(app.chrome.proxy.settings.value.mode, undefined);
  }
});

test('a stopped core or changed health-check port blocks traffic', async () => {
  for (const connected of [true, false]) {
    const app = background(); await app.ready;
    const backend = helper(app);
    await app.send({command:'refresh'}); await app.send({command:'connect', index:0});
    backend.state.connected = connected; backend.state.port = 25678;
    app.listeners.alarm({name:'health'});
    await vm.runInContext('serial', app.context);
    await vm.runInContext('blocking', app.context);
    assert.equal((await app.send({command:'getState'})).mode, 'blocked');
    assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 0);
  }
});

test('losing the helper while Chrome applies a new port cannot report a connected VPN', async () => {
  for (const command of ['connect', 'refresh']) {
    const app = background({vpnEnabled:true}); await app.ready;
    const backend = helper(app);
    await app.send({command:'refresh'});
    const settings = app.chrome.proxy.settings;
    const set = settings.set.bind(settings);
    let interrupted = false;
    settings.set = async options => {
      await set(options);
      if (options.value.rules.singleProxy.port > 0 && !interrupted) {
        interrupted = true;
        backend.native.disconnect();
      }
    };
    if (command === 'refresh') backend.state.connected = true;
    const result = await app.send({command, index:0});
    await vm.runInContext('blocking', app.context);
    assert.equal(result.mode, 'blocked');
    assert.equal(settings.value.rules.singleProxy.port, 0);
    assert.equal(app.storage.vpnEnabled, true);
  }
});
