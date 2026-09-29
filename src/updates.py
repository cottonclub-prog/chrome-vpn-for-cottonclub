"""Only official CottonClub releases; no caller-controlled URLs or commands."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import ProxyHandler, Request, build_opener

REPOSITORY = 'cottonclub-prog/chrome-vpn-for-cottonclub'
ASSET = 'Chrome-vpn-for-cottonclub-hysteria2-user-Windows-x64.zip'


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('Invalid version')
    return tuple(map(int, value.split('.')))


def parse_release(release, current):
    version_tuple(current)
    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('Not a stable release')
    tag = release.get('tag_name', '')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Invalid release tag')
    version = tag[1:]
    newer = version_tuple(version) > version_tuple(current)
    url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{ASSET}'
    asset = next((a for a in release.get('assets', []) if a.get('name') == ASSET), None)
    if not asset or asset.get('browser_download_url') != url or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', asset.get('digest', '')):
        raise ValueError('Verified official package missing')
    return {'version': version, 'available': newer}


def check_update(current):
    try:
        request = Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                          headers={'User-Agent': 'CottonClub-Updater', 'Accept': 'application/vnd.github+json'})
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('Response too large')
        return parse_release(json.loads(body), current)
    except Exception:
        raise RuntimeError('Не удалось проверить обновления GitHub. Проверьте интернет или повторите позже.') from None


def launch_update():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Обновление доступно после установки готового комплекта.')
    base = Path(sys.executable).resolve().parents[3]
    expected = Path(os.environ['LOCALAPPDATA']) / 'Chrome VPN for CottonClub'
    script = base / 'Update.ps1'
    if base != expected.resolve() or not script.is_file():
        raise RuntimeError('Файлы обновления не найдены. Запустите Install.cmd из свежего репозитория.')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                      '-WaitForHostPid', str(os.getpid())], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000000, close_fds=True)
    return {'started': True}
