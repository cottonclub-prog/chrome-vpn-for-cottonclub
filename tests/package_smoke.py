"""Inspect the release and exercise its EXE without installation or Chrome changes."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import pefile

ROOT = Path(__file__).resolve().parents[1]
archive = ROOT / 'dist/cottonclub-vpn-for-chrome-windows-x64.zip'
with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
    destination = Path(directory)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for item in z.infolist():
            assert (destination / item.filename).resolve().is_relative_to(destination.resolve())
        z.extractall(destination)
    package = destination / 'cottonclub-vpn-for-chrome'
    entries = json.loads((package / 'payload.json').read_text(encoding='utf-8-sig'))
    for item in entries:
        assert hashlib.sha256((package / item['path']).read_bytes()).hexdigest() == item['sha256'].lower()
    assert {p.name for p in (package / 'host').glob('*.exe')} == {'cottonclub-vpn-for-chrome-host.exe'}
    assert {p.name for p in (package / 'host/bin').glob('*.exe')} == {'sing-box.exe'}
    assert not list(package.rglob('*xray*'))
    assert json.loads((package / 'host/routing/default-rules.json').read_text(encoding='utf-8')) == json.loads((package / 'CottonClub VPN for Chrome/routing-defaults.json').read_text(encoding='utf-8'))
    policy = json.loads((package / 'host/routing/ru-direct.json').read_text(encoding='utf-8'))
    assert not any(policy[key] for key in ('domain', 'domain_suffix', 'domain_regex', 'domain_keyword'))
    args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(package / 'Install.ps1'), '-VerifyOnly']
    verified = subprocess.run(args, capture_output=True, timeout=30)
    assert verified.returncode == 0, verified.stderr
    executable = package / 'host/cottonclub-vpn-for-chrome-host.exe'
    # Windows must not elevate the shipped helper or VPN core.
    for binary in (executable, package / 'host/bin/sing-box.exe'):
        with pefile.PE(str(binary)) as pe:
            for resource in getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', ()).entries if hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE') else ():
                if resource.id != 24:  # RT_MANIFEST
                    continue
                for name in resource.directory.entries:
                    for language in name.directory.entries:
                        data = language.data.struct
                        manifest = ET.fromstring(pe.get_data(data.OffsetToData, data.Size).rstrip(b'\0'))
                        levels = manifest.findall('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
                        assert all(item.get('level') == 'asInvoker' for item in levels), binary
    messages = [{'id': 1, 'action': 'status'},
                {'id': 2, 'action': 'load', 'subscription': 'hysteria2://test-password@127.0.0.1:443?sni=localhost#Smoke'},
                {'id': 3, 'action': 'disconnect'},
                {'id': 4, 'action': 'load', 'subscription': 'vless://11111111-1111-4111-8111-111111111111@127.0.0.1:443?security=none'},
                {'id': 5, 'action': 'validateRouting', 'rules': [{'type': 'domain', 'value': '.рф', 'outbound': 'vpn', 'enabled': True}]},
                {'id': 6, 'action': 'validateRouting', 'rules': [{'type': 'ip', 'value': 'invalid', 'outbound': 'direct', 'enabled': True}]}]
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
    assert len(responses) == 6 and all(r['ok'] for r in responses[:3]), responses
    assert not responses[3]['ok'], 'VLESS must be rejected by the shipped EXE'
    assert responses[4]['ok'] and responses[4]['result']['rules'][0]['value'] == 'xn--p1ai'
    assert not responses[5]['ok'], 'Invalid routing rules must be rejected by the shipped EXE'
    assert responses[0]['result']['port'] == 17892
    assert responses[1]['result']['nodes'][0]['name'] == 'Smoke'
    rejected = subprocess.run([str(executable), 'chrome-extension://wrong/'], input=b'',
                              capture_output=True, timeout=20, creationflags=0x08000000)
    assert rejected.returncode == 2
    corporate = subprocess.run([str(executable), 'chrome-extension://pppgaipmgmbndhejmkabemifkonbgooh/'],
                               input=payload[:4 + struct.unpack('<I', payload[:4])[0]], capture_output=True,
                               timeout=20, creationflags=0x08000000)
    assert corporate.returncode == 0, corporate.stderr
    assert json.loads(corporate.stdout[4:])['ok'], 'CRX origin must be accepted'
    # HTTPS subscription attempts must create identity only in the new app root.
    # The closed loopback port fails without contacting any outside server.
    identity_parent = destination / 'localappdata'
    identity_parent.mkdir()
    body = json.dumps({'id': 7, 'action': 'load', 'subscription': 'https://127.0.0.1:1/'}).encode()
    checked = subprocess.run([str(executable), 'chrome-extension://hooimhadihhgfkhidbmjoaojfljafnaf/'],
                             input=struct.pack('<I', len(body)) + body, capture_output=True, timeout=20,
                             env={**os.environ, 'LOCALAPPDATA': str(identity_parent)}, creationflags=0x08000000)
    assert checked.returncode == 0, checked.stderr
    assert not json.loads(checked.stdout[4:])['ok']
    identity = identity_parent / 'CottonClub VPN for Chrome/device-id.txt'
    assert len(identity.read_text(encoding='ascii').strip()) == 32
    assert [p.name for p in identity_parent.iterdir()] == ['CottonClub VPN for Chrome']
    # Damaged packages must fail before any Windows mutations.
    (package / 'CottonClub VPN for Chrome/popup.js').write_text('damaged', encoding='utf-8')
    damaged = subprocess.run(args, capture_output=True, timeout=30)
    assert damaged.returncode != 0
print('ZIP CRC, hashes, installer verification/rejection, EXE framing and origin checks passed.')
