"""Exercise the real routing page in isolated headless Chrome with mocked extension RPC."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
browser = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Google/Chrome/Application/chrome.exe'
if not browser.is_file():
    raise RuntimeError('Google Chrome is required for this UI check.')
fixture = ROOT / 'build' / ('routing-ui-' + uuid.uuid4().hex)
fixture.mkdir(parents=True)
for name in ('popup.css', 'routing.css', 'routing.js', 'routing-defaults.json'):
    shutil.copyfile(ROOT / 'extension' / name, fixture / name)
defaults = json.loads((fixture / 'routing-defaults.json').read_text(encoding='utf-8'))
(fixture / 'fixture.js').write_text('const initialRules = ' + json.dumps(defaults) + r''';
window.storedRules = structuredClone(initialRules);
window.confirm = () => true;
window.chrome.runtime = {sendMessage: async message => {
  if (message.command === 'saveRouting') {
    window.storedRules = structuredClone(message.rules);
    return {saved:true, routingRules:storedRules, message:'Saved'};
  }
  return {routingRules: storedRules, mode:'off'};
}};
window.fetch = async () => ({ok:true, json:async () => structuredClone(initialRules)});
window.addEventListener('load', async () => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const settle = () => new Promise(resolve => setTimeout(resolve, 0));
  try {
    await settle();
    assert(document.querySelectorAll('.rule').length === 4, 'Four defaults visible');
    document.getElementById('add-rule').click();
    const last = document.querySelector('.rule:last-child');
    const input = last.querySelector('input[type=text]');
    input.value = 'example.ru'; input.dispatchEvent(new Event('input'));
    const selects = last.querySelectorAll('select');
    selects[1].value = 'vpn'; selects[1].dispatchEvent(new Event('change'));
    last.querySelector('.actions button').click();
    document.getElementById('save-rules').click(); await settle();
    assert(storedRules[3].value === 'example.ru' && storedRules[3].outbound === 'vpn', 'Edit, reorder and save');
    while (document.querySelector('.rule')) document.querySelector('.rule .actions button:last-child').click();
    document.getElementById('save-rules').click(); await settle();
    assert(storedRules.length === 0, 'Empty list saved');
    document.getElementById('reset-rules').click(); await settle();
    document.getElementById('save-rules').click(); await settle();
    assert(storedRules.length === 4 && storedRules[0].type === 'geoip-ru', 'Defaults restored');
    assert(document.documentElement.scrollWidth <= window.innerWidth, 'No horizontal overflow');
    document.body.dataset.testResult = 'passed';
  } catch (error) { document.body.dataset.testResult = error.message; }
});
''', encoding='utf-8')
html = (ROOT / 'extension/routing.html').read_text(encoding='utf-8')
html = html.replace('<script src="routing.js">', '<script src="fixture.js"></script><script src="routing.js">')
(fixture / 'routing.html').write_text(html, encoding='utf-8')
for width in (1100, 560):
    result = subprocess.run([str(browser), '--headless=new', '--disable-gpu', '--no-first-run',
                             '--no-default-browser-check', '--allow-file-access-from-files',
                             '--user-data-dir=' + str(fixture / ('profile-' + str(width))),
                             f'--window-size={width},1000', '--virtual-time-budget=3000', '--dump-dom',
                             '--screenshot=' + str(fixture / f'routing-{width}.png'),
                             (fixture / 'routing.html').as_uri()], capture_output=True, timeout=60,
                            creationflags=0x08000000)
    dom = result.stdout.decode('utf-8', errors='replace')
    if result.returncode or 'data-test-result="passed"' not in dom:
        raise RuntimeError(f'Routing UI check failed at width {width}: {dom[-2000:]} {result.stderr[-1000:]}')
print('Routing page add/edit/reorder/delete/save/reset passed at desktop and narrow widths.')
print(fixture)
