const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = name => fs.readFileSync(path.join(__dirname, '../extension', name), 'utf8');

function background(saved = {}, savedSession = {}) {
  const listeners = {};
  const storage = {...saved};
  const setting = () => ({
    value: {}, levelOfControl: 'controllable_by_this_extension',
    async get() { return {value: this.value, levelOfControl: this.levelOfControl}; },
    async set({value}) { this.value = value; this.levelOfControl = 'controlled_by_this_extension'; },
    async clear() { this.value = {}; this.levelOfControl = 'controllable_by_this_extension'; },
    onChange: {addListener() {}},
  });
  const chrome = {
    storage: {
      local: {async setAccessLevel() {}, async get() { return {...storage}; }, async set(value) { Object.assign(storage, value); }},
      session: {async setAccessLevel() {}, async get() { return {...savedSession}; }, async set(value) { Object.assign(savedSession, value); }, async remove(key) { delete savedSession[key]; }},
    },
    action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}, async setTitle() {}},
    proxy: {settings: setting()},
    privacy: {network: {webRTCIPHandlingPolicy: setting(), networkPredictionEnabled: setting()}},
    alarms: {create() {}, onAlarm: {addListener() {}}},
    runtime: {id: 'test', getManifest: () => ({version: '1.0.3'}), getURL: () => 'chrome-extension://test/',
      onMessage: {addListener(fn) { listeners.message = fn; }}, onStartup: {addListener() {}},
      connectNative() { throw new Error('Helper unavailable'); }},
  };
  const context = vm.createContext({chrome, setTimeout, clearTimeout});
  vm.runInContext(source('background.js'), context);
  return {chrome, storage, context,
    ready: vm.runInContext('ready', context),
    send(message) { return new Promise(resolve => listeners.message(message,
      {id: 'test', url: 'chrome-extension://test/popup.html'}, resolve)); },
  };
}

test('restart with enabled VPN retains a blocking proxy until explicit disconnect', async () => {
  const app = background({vpnEnabled: true});
  await app.ready;
  assert.equal((await app.send({command: 'getState'})).mode, 'blocked');
  assert.equal(app.chrome.proxy.settings.value.rules.singleProxy.port, 17892);
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

test('popup restores selection even when the node list has not changed', async () => {
  const elements = new Map();
  const element = () => ({value: '', addEventListener() {}, replaceChildren() {}, append() {}});
  const context = vm.createContext({
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, createElement: element},
    chrome: {runtime: {sendMessage: async () => undefined}},
    navigator: {}, setInterval() {},
  });
  vm.runInContext(source('popup.js'), context);
  await new Promise(resolve => setImmediate(resolve));
  const state = {mode: 'off', nodes: [{index: 0, name: 'First', protocol: 'hysteria2'}, {index: 1, name: 'Second', protocol: 'hysteria2'}], selected: 0};
  context.state = state;
  vm.runInContext('render(state)', context);
  state.selected = 1;
  vm.runInContext('render(state)', context);
  assert.equal(elements.get('server').value, '1');
});
