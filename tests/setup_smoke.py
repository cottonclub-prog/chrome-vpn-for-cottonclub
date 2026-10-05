"""Verify the graphical EXE payload without installing or changing Windows."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import pefile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / 'extension/manifest.json').read_text(encoding='utf-8'))['version']
setup = ROOT / 'dist' / f'COTTONCLUB-VPN-Setup-{version}.exe'
with pefile.PE(str(setup)) as pe:
    levels = []
    for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource.id == 24:
            for name in resource.directory.entries:
                for language in name.directory.entries:
                    data = language.data.struct
                    manifest = ET.fromstring(pe.get_data(data.OffsetToData, data.Size).rstrip(b'\0'))
                    levels += [element.get('level') for element in manifest.findall('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')]
    assert levels == ['asInvoker'], levels
result = subprocess.run([str(setup), '--verify-only'], timeout=180, creationflags=0x08000000)
assert result.returncode == 0, 'EXE embedded payload verification failed'
identity = json.loads((ROOT / 'installer/crx-identity.json').read_text(encoding='utf-8'))
subprocess.run(['node', str(ROOT / 'installer/verify-crx.cjs'), str(ROOT / 'dist/COTTONCLUB-VPN.crx'), identity['id']], check=True)
update = ET.fromstring((ROOT / 'dist/updates.xml').read_text(encoding='utf-8'))
app = update.find('{http://www.google.com/update2/response}app')
assert app.get('appid') == identity['id']
assert app[0].get('version') == version
print('EXE asInvoker, embedded ZIP/installer verification, CRX3 signature and update XML passed.')
