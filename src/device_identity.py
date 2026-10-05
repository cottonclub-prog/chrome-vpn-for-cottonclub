"""A persistent random installation identifier for subscription device limits."""
from pathlib import Path
import platform
import uuid

from app_paths import APP_DIRECTORY, APP_NAME


def device_id(directory=None):
    if directory is None:
        directory = APP_DIRECTORY
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'device-id.txt'
    if not path.exists():
        try:
            with path.open('x', encoding='ascii') as output:
                output.write(uuid.uuid4().hex)
        except FileExistsError:
            pass
    value = path.read_text(encoding='ascii').strip()
    # Never silently rotate identity: that would consume another device slot.
    if len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid saved device identifier')
    return value


def subscription_headers():
    return {
        'User-Agent': 'cottonclub-vpn-for-chrome/1.6.1',
        'Accept': 'text/plain',
        'X-Hwid': device_id(),
        'X-Device-Os': 'Windows',
        'X-Ver-Os': platform.release(),
        'X-Device-Model': APP_NAME,
    }
