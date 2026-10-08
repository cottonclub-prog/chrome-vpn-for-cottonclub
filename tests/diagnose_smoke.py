"""Exercise standalone diagnosis with a packaged helper and silent loopback HY2."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / 'CottonClub VPN for Chrome/manifest.json').read_text(encoding='utf-8'))['version']
with tempfile.TemporaryDirectory(prefix='diagnose-smoke-', dir=ROOT / 'build') as directory:
    fixture = Path(directory)
    with zipfile.ZipFile(ROOT / 'dist/cottonclub-vpn-for-chrome-windows-x64.zip') as archive:
        for item in archive.infolist():
            assert (fixture / item.filename).resolve().is_relative_to(fixture.resolve())
        archive.extractall(fixture)
    package = fixture / 'cottonclub-vpn-for-chrome'
    assert json.loads((package / 'CottonClub VPN for Chrome/manifest.json').read_text(encoding='utf-8'))['version'] == version
    identity = package / 'device-id.txt'
    identity.write_text('fixture-identity-never-change', encoding='ascii')
    before = hashlib.sha256(identity.read_bytes()).hexdigest()
    quote = lambda path: "'" + str(path).replace("'", "''") + "'"
    # Hold a UDP endpoint so the test cannot accidentally contact another process.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as silent:
        silent.bind(('127.0.0.1', 0))
        port = silent.getsockname()[1]
        wrapper = fixture / 'test.ps1'
        wrapper.write_text("""$ErrorActionPreference = 'Stop'
function global:Read-Host {
    param($Prompt, [switch]$AsSecureString)
    ConvertTo-SecureString 'hy2://diag-fixture@127.0.0.1:""" + str(port) + """?sni=localhost' -AsPlainText -Force
}
& """ + quote(ROOT / 'Diagnose.ps1') + ' -InstallDirectory ' + quote(package) + '\n', encoding='ascii')
        result = subprocess.run([os.environ['SystemRoot'] + '/System32/WindowsPowerShell/v1.0/powershell.exe',
                                 '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)],
                                capture_output=True, timeout=240, creationflags=0x08000000)
    report = result.stdout.decode(errors='replace')
    assert result.returncode == 0, result.stderr
    assert 'Link parsed by the installed helper: OK' in report, report
    assert 'Installed helper HTTPS check: SOCKS_CONNECT_TIMEOUT' in report, report
    assert 'Diagnostic core listener: OK' in report, report
    assert 'ipify via same core: SOCKS_CONNECT/' in report, report
    assert 'Cloudflare via same core: SOCKS_CONNECT/' in report, report
    assert 'NETWORK_TIMEOUT' in report, report
    assert 'diag-fixture' not in report
    assert 'hy2://' not in report.replace('hysteria2:// or hy2://', '')
    assert '127.0.0.1:' + str(port) not in report
    assert 'TRANSIENT_CONFIG_NOT_CAPTURED' not in report
    assert hashlib.sha256(identity.read_bytes()).hexdigest() == before
    assert not list(package.glob('core-*.json'))
print('Packaged helper, exact config capture, failure phases, hidden secrets and preserved identity passed.')
