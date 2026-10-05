"""Download the pinned official core, verifying GitHub's published asset digest."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

VERSION = '1.14.1'
ROOT = Path(__file__).resolve().parent


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'cottonclub-vpn-for-chrome-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    release = json.loads(get(f'https://api.github.com/repos/SagerNet/sing-box/releases/tags/v{VERSION}'))
    name = f'sing-box-{VERSION}-windows-amd64.zip'
    asset = next(a for a in release['assets'] if a['name'] == name)
    digest = asset.get('digest', '')
    if not digest.startswith('sha256:'):
        raise RuntimeError('GitHub did not provide SHA-256; refusing an unverified download')
    archive = get(asset['browser_download_url'])
    actual = 'sha256:' + hashlib.sha256(archive).hexdigest()
    if actual != digest:
        raise RuntimeError('Archive SHA-256 mismatch')
    target = ROOT / 'bin'
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        exe = next(n for n in z.namelist() if n.endswith('/sing-box.exe'))
        (target / 'sing-box.exe').write_bytes(z.read(exe))
    (target / 'LICENSE-sing-box.txt').write_bytes(get(f'https://raw.githubusercontent.com/SagerNet/sing-box/v{VERSION}/LICENSE'))
    (target / 'SOURCE.txt').write_text(
        f'sing-box {VERSION}\nhttps://github.com/SagerNet/sing-box/tree/v{VERSION}\n'
        f'Source archive: https://github.com/SagerNet/sing-box/archive/refs/tags/v{VERSION}.tar.gz\n'
        f'Binary: {asset["browser_download_url"]}\n{digest}\n', encoding='utf-8')
    print(f'sing-box {VERSION}: verified and installed in {target}')


if __name__ == '__main__':
    main()
