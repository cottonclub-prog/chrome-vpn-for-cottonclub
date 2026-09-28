"""Inspect the release and exercise its EXE without installation or Chrome changes."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
archive = ROOT / 'dist/Chrome-vpn-for-cottonclub-Windows-x64.zip'
with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
    destination = Path(directory)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for item in z.infolist():
            assert (destination / item.filename).resolve().is_relative_to(destination.resolve())
        z.extractall(destination)
    package = destination / 'Chrome-vpn-for-cottonclub'
    entries = json.loads((package / 'payload.json').read_text(encoding='utf-8-sig'))
    for item in entries:
        assert hashlib.sha256((package / item['path']).read_bytes()).hexdigest() == item['sha256'].lower()
    assert not list(package.rglob('Project-ZXC-for-Chrome.exe'))
    args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(package / 'Install.ps1'), '-VerifyOnly']
    verified = subprocess.run(args, capture_output=True, timeout=30)
    assert verified.returncode == 0, verified.stderr
    executable = package / 'host/ZXC-AdminHost.exe'
    messages = [{'id': 1, 'action': 'status'},
                {'id': 2, 'action': 'load', 'subscription': 'vless://11111111-1111-4111-8111-111111111111@127.0.0.1:443?security=none#Smoke'},
                {'id': 3, 'action': 'disconnect'}]
    payload = b''
    for message in messages:
        body = json.dumps(message).encode()
        payload += struct.pack('<I', len(body)) + body
    result = subprocess.run([str(executable), 'chrome-extension://hooimhadihhgfkhidbmjoaojfljafnaf/'],
                            input=payload, capture_output=True, timeout=20, creationflags=0x08000000)
    assert result.returncode == 0, result.stderr
    data = result.stdout
    responses = []
    while data:
        size, = struct.unpack('<I', data[:4])
        responses.append(json.loads(data[4:4 + size]))
        data = data[4 + size:]
    assert len(responses) == 3 and all(r['ok'] for r in responses), responses
    assert responses[0]['result']['port'] == 17892
    assert responses[1]['result']['nodes'][0]['name'] == 'Smoke'
    rejected = subprocess.run([str(executable), 'chrome-extension://wrong/'], input=b'',
                              capture_output=True, timeout=20, creationflags=0x08000000)
    assert rejected.returncode == 2
    # Damaged packages must fail before elevation or any Windows mutations.
    (package / 'extension/popup.js').write_text('damaged', encoding='utf-8')
    damaged = subprocess.run(args, capture_output=True, timeout=30)
    assert damaged.returncode != 0
print('ZIP CRC, hashes, installer verification/rejection, EXE framing and origin checks passed.')
