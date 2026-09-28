"""Pinned official Xray build compatible with the server's Reality protocol."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from prepare import get

VERSION = '26.9.9'


def main():
    release = json.loads(get(f'https://api.github.com/repos/XTLS/Xray-core/releases/tags/v{VERSION}'))
    asset = next(a for a in release['assets'] if a['name'] == 'Xray-windows-64.zip')
    digest = asset.get('digest', '')
    if not digest.startswith('sha256:'):
        raise RuntimeError('Missing published SHA-256')
    archive = get(asset['browser_download_url'])
    if 'sha256:' + hashlib.sha256(archive).hexdigest() != digest:
        raise RuntimeError('SHA-256 mismatch')
    target = Path(__file__).resolve().parent / 'bin'
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        (target / 'xray.exe').write_bytes(z.read('xray.exe'))
        license_name = next(n for n in z.namelist() if Path(n).name.lower().startswith('license'))
        (target / 'LICENSE-xray.txt').write_bytes(z.read(license_name))
    (target / 'SOURCE-xray.txt').write_text(
        f'Xray-core {VERSION}\nhttps://github.com/XTLS/Xray-core/tree/v{VERSION}\n'
        f'{asset["browser_download_url"]}\n{digest}\n', encoding='utf-8')
    print(f'Official Xray {VERSION} downloaded and SHA-256 verified.')


if __name__ == '__main__':
    main()
