"""Verify the graphical EXE payload without installing or changing Windows."""
import json
from pathlib import Path
import subprocess
import struct
import xml.etree.ElementTree as ET
import pefile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / 'CottonClub VPN for Chrome/manifest.json').read_text(encoding='utf-8'))['version']
setup = ROOT / 'dist' / f'cottonclub-vpn-for-chrome-setup-{version}.exe'
with pefile.PE(str(setup)) as pe:
    levels = []
    embedded_icons = set()
    for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource.id == 3:  # RT_ICON: verify the EXE contains the actual new logo.
            for name in resource.directory.entries:
                for language in name.directory.entries:
                    data = language.data.struct
                    embedded_icons.add(pe.get_data(data.OffsetToData, data.Size))
        if resource.id == 24:
            for name in resource.directory.entries:
                for language in name.directory.entries:
                    data = language.data.struct
                    manifest = ET.fromstring(pe.get_data(data.OffsetToData, data.Size).rstrip(b'\0'))
                    levels += [element.get('level') for element in manifest.findall('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')]
    assert levels == ['asInvoker'], levels
    ico = (ROOT / 'CottonClub VPN for Chrome/icons/app.ico').read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', ico)
    assert (reserved, kind) == (0, 1)
    expected_icons, icon_sizes = set(), set()
    for index in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', ico, 6 + 16 * index)
        size = width or 256
        assert size == (height or 256)
        png = ico[offset:offset + length]
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', png[16:24]) == (size, size)
        expected_icons.add(png)
        icon_sizes.add(size)
        if size in (16, 32, 48, 128):
            assert png == (ROOT / 'CottonClub VPN for Chrome/icons' / f'icon-{size}.png').read_bytes()
    assert {16, 20, 24, 32, 40, 48, 64, 96, 128, 256} == icon_sizes
    assert embedded_icons == expected_icons, 'EXE icon resources differ from the extension logo'
result = subprocess.run([str(setup), '--verify-only'], timeout=180, creationflags=0x08000000)
assert result.returncode == 0, 'EXE embedded payload verification failed'
identity = json.loads((ROOT / 'installer/crx-identity.json').read_text(encoding='utf-8'))
subprocess.run(['node', str(ROOT / 'installer/verify-crx.cjs'), str(ROOT / 'dist/cottonclub-vpn-for-chrome.crx'), identity['id']], check=True)
update = ET.fromstring((ROOT / 'dist/updates.xml').read_text(encoding='utf-8'))
app = update.find('{http://www.google.com/update2/response}app')
assert app.get('appid') == identity['id']
assert app[0].get('version') == version
print('EXE asInvoker, embedded ZIP/installer verification, CRX3 signature and update XML passed.')
