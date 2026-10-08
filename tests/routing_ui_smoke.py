"""Exercise the production popup in isolated Chrome with mocked extension RPC."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
browser = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Google/Chrome/Application/chrome.exe'
fixture = ROOT / 'build' / ('popup-ui-' + uuid.uuid4().hex)
fixture.mkdir(parents=True)
for name in ('popup.css', 'popup.js', 'routing-defaults.json'):
    shutil.copyfile(ROOT / 'CottonClub VPN for Chrome' / name, fixture / name)
shutil.copytree(ROOT / 'CottonClub VPN for Chrome/icons', fixture / 'icons')
defaults = json.loads((fixture / 'routing-defaults.json').read_text(encoding='utf-8'))
script = r'''const initialRules = DEFAULTS;
const state = {mode:'off',nodes:[],selected:0,routingMode:'ru-direct',routingRules:structuredClone(initialRules),currentVersion:'1.4.0',subscription:'https://example.com/sub'};
window.confirm=()=>true;
window.fetch=async()=>({ok:true,json:async()=>structuredClone(initialRules)});
let rejectSave=false;
window.chrome.runtime={getManifest:()=>({version:'1.4.0'}),sendMessage:async m=>{
  if(m.command==='load')state.nodes=[{index:4,name:'DE Germany'},{index:7,name:'NL Amsterdam'}],state.selected=4;
  if(m.command==='select')state.selected=m.index;
  if(m.command==='connect')state.mode='on',state.ip='203.0.113.1';
  if(m.command==='disconnect')state.mode='off';
  if(m.command==='routing')state.routingMode=m.mode;
  if(m.command==='saveRouting'){
    if(rejectSave)return {...structuredClone(state),saved:false,message:'Invalid IP'};
    state.routingRules=structuredClone(m.rules);return {...structuredClone(state),saved:true};
  }
  if(m.command==='checkUpdate')state.update={available:true,version:'1.5.0'};
  if(m.command==='installUpdate')state.updating=true,state.updateReady=false;
  if(m.command==='finishUpdate')state.updating=false;
  return structuredClone(state);
}};
window.addEventListener('load',async()=>{
 const settle=()=>new Promise(r=>setTimeout(r,0));const assert=(v,m)=>{if(!v)throw Error(m)};
 try{
  await settle(); await settle();
  assert($('power').disabled,'empty subscription disables connect');
  screen('settings');$('show-sub').click();assert($('subscription').type==='text','reveal link');$('show-sub').click();
  $('load-sub').click();await settle();screen('vpn');$('server-picker').click();
  assert(document.querySelectorAll('.location-option').length===2,'real nodes');
  document.querySelectorAll('.location-option')[1].click();await settle();assert(currentState.selected===7,'selection uses index');state.selected=4;renderState(structuredClone(state));assert($('server-name').textContent==='DE Germany','selection refresh with unchanged nodes');
  $('power').click();await settle();assert(currentState.mode==='on','connect');assert(getComputedStyle($('power')).color==='rgb(255, 255, 255)','white icon');
  assert($('server-picker').disabled&&$('save-rules').disabled,'active restrictions');
  $('power').click();await settle();assert(currentState.mode==='off','disconnect');
  state.mode='blocked';renderState(structuredClone(state));$('power').click();await settle();assert(state.mode==='off','blocked can disconnect');
  screen('rules');$('add-rule').click();$('address-trigger').click();addressOptions[1].click();assert($('rule-type').value==='ip','custom dropdown');
  $('address-trigger').click();addressOptions[1].dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
  addressOptions[0].dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));assert($('rule-type').value==='domain','keyboard selection');
  $('rule-value').value='example.ru';document.querySelector('[data-direction=vpn]').click();$('rule-form').requestSubmit();
  openEditor(4);$('move-up').click();$('close-editor').click();$('save-rules').click();await settle();
  assert(state.routingRules[3].value==='example.ru'&&state.routingRules[3].outbound==='vpn','edit reorder save');
  openEditor(3);$('rule-enabled').click();$('rule-form').requestSubmit();$('save-rules').click();await settle();assert(!state.routingRules[3].enabled,'disable saved');
  openEditor(3);$('rule-value').value='invalid';$('rule-form').requestSubmit();rejectSave=true;$('save-rules').click();await settle();assert(rulesDirty&&$('rule-note').textContent==='Invalid IP','validation retains unsaved data');rejectSave=false;
  while(rules.length){openEditor(0);$('delete-rule').click()};$('save-rules').click();await settle();assert(!state.routingRules.length,'empty rules saved');
  $('reset-rules').click();await settle();$('save-rules').click();await settle();assert(state.routingRules.length===4,'reset');
  screen('settings');$('check-update').click();await settle();assert(!$('install-update').hidden,'update available');$('install-update').click();await settle();assert($('finish-update').disabled,'no premature reload');
  state.updateReady=true;renderState(structuredClone(state));assert(!$('finish-update').disabled,'ready reload');$('finish-update').click();await settle();
  screen('rules');openEditor(-1);$('address-trigger').click();addressOptions[0].dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(!$('editor').hidden&&$('address-options').hidden,'escape closes dropdown only');
  closeEditor();assert($('app').scrollWidth<=$('app').clientWidth,'no horizontal overflow');
  const note=$('rule-note').getBoundingClientRect();assert(note.bottom<=document.querySelector('.footer').getBoundingClientRect().top,'save note fits');
  state.mode='blocked';state.message='Hysteria 2/sing-box, По правилам:\nПрокси не подтвердил соединение. [SOCKS_CONNECT_TIMEOUT]\n'+'Ядро не дождалось ответа сети. Точная причина не подтверждена. [NETWORK_TIMEOUT] '.repeat(4);renderState(structuredClone(state));screen('vpn');
  const message=$('status');assert(message.dataset.kind==='error','error presentation');assert(getComputedStyle(message).whiteSpace==='pre-line','failure stages on separate lines');
  assert(message.getBoundingClientRect().height<=129,'bounded error panel');assert(message.scrollHeight>message.clientHeight,'long error is scrollable');
  message.scrollTop=message.scrollHeight;assert(message.scrollTop>0,'all error text reachable');assert(message.getBoundingClientRect().bottom<=document.querySelector('.footer').getBoundingClientRect().top+1,'footer remains visible');
  assert($('app').scrollWidth<=$('app').clientWidth,'error codes fit popup');document.body.dataset.testResult='passed';
 }catch(e){document.body.dataset.testResult=e.stack;}
});
'''.replace('DEFAULTS',json.dumps(defaults))
(fixture/'fixture.js').write_text(script,encoding='utf-8')
html=(ROOT/'CottonClub VPN for Chrome/popup.html').read_text(encoding='utf-8').replace('<script src="popup.js">','<script src="fixture.js"></script><script src="popup.js">')
(fixture/'popup.html').write_text(html,encoding='utf-8')
result=subprocess.run([str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--allow-file-access-from-files','--user-data-dir='+str(fixture/'profile'),'--window-size=800,800','--virtual-time-budget=4000','--dump-dom','--screenshot='+str(fixture/'popup.png'),(fixture/'popup.html').as_uri()],capture_output=True,timeout=60,creationflags=0x08000000)
dom=result.stdout.decode('utf-8',errors='replace')
if result.returncode or 'data-test-result="passed"' not in dom:
    import re
    raise RuntimeError(str(re.findall(r'data-test-result="([^"]*)"',dom))+str(result.stderr[-500:]))
print('Popup connection, blocked disconnect, routing CRUD, validation, keyboard and update gating passed.')
print(fixture)
