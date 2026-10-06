"""Exercise the production launch function in an off-screen, isolated Chrome."""
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
fixture = ROOT / 'build' / ('launch-window-' + uuid.uuid4().hex)
fixture.mkdir()
profile = fixture / 'profile'
browser = Path(os.environ['ProgramFiles']) / 'Google/Chrome/Application/chrome.exe'
arguments = ['--user-data-dir="' + str(profile) + '"', '--remote-debugging-port=0',
             '--no-first-run', '--no-default-browser-check', '--window-position=-32000,-32000']
(fixture / 'arguments.json').write_text(json.dumps(arguments), encoding='utf-8')
probe = fixture / 'probe.ps1'
probe.write_text(r'''
param([string]$Launcher, [string]$Chrome, [string]$ArgumentsFile)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Launcher, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Launcher syntax error' }
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Open-ChromeExtensionsWindow'}, $true)
. ([scriptblock]::Create($function.Extent.Text))
$arguments = @(Get-Content -LiteralPath $ArgumentsFile -Raw -Encoding UTF8 | ConvertFrom-Json)
Open-ChromeExtensionsWindow -Chrome $Chrome -AdditionalArguments $arguments
''', encoding='utf-8')
endpoint = None
def targets():
    with urlopen(endpoint + '/json/list', timeout=3) as response:
        return json.load(response)
def launch():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(probe), '-Launcher', str(ROOT / 'Launch.ps1'),
                             '-Chrome', str(browser), '-ArgumentsFile', str(fixture / 'arguments.json')],
                            capture_output=True, timeout=90, creationflags=0x08000000)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
def wait_for(condition):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            value = condition()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise TimeoutError(repr(targets()) if endpoint else 'Chrome endpoint unavailable')
try:
    launch()
    port = wait_for(lambda: (profile / 'DevToolsActivePort').read_text().splitlines()[0])
    endpoint = 'http://127.0.0.1:' + port
    first = wait_for(lambda: next((t for t in targets() if t['url'] == 'chrome://extensions/'), None))
    # A second call must create a separate extensions window while Chrome is running.
    launch()
    second = wait_for(lambda: next((t for t in targets() if t['url'] == 'chrome://extensions/' and t['id'] != first['id']), None))
    print('Production launcher opened chrome://extensions/ on fresh launch and in an already running Chrome.')
finally:
    port_file = profile / 'DevToolsActivePort'
    if not endpoint and port_file.exists():
        endpoint = 'http://127.0.0.1:' + port_file.read_text().splitlines()[0]
    if endpoint:
        try:
            with urlopen(endpoint + '/json/version', timeout=3) as response:
                websocket = json.load(response)['webSocketDebuggerUrl']
            subprocess.run(['node', '-e', "const ws=new WebSocket(process.argv[1]); ws.onopen=()=>ws.send(JSON.stringify({id:1,method:'Browser.close'})); ws.onmessage=()=>ws.close(); ws.onerror=()=>process.exit(1);", websocket],
                           check=True, timeout=15, creationflags=0x08000000, capture_output=True)
        except OSError:
            pass
