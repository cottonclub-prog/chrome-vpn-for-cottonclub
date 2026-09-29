"""Chrome Native Messaging host. Only framed JSON is written to stdout."""
import json
import os
import struct
import sys
import threading

from host_config import EXTENSION_ID, EXTENSION_PORT
from runtime import Core, DATA, check_connection
from subscription import fetch_subscription, SubscriptionError
from routing_policy import DEFAULT_MODE, MODES
from diagnostics import ConnectionCheckError
from updates import check_update, launch_update

MAX_MESSAGE = 2 * 1024 * 1024


def read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        part = stream.read(length - len(result))
        if not part:
            if not result:
                return None
            raise ValueError('Truncated message')
        result.extend(part)
    return bytes(result)


def read_message(stream):
    header = read_exact(stream, 4)
    if header is None:
        return None
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError('Message too large')
    body = read_exact(stream, size)
    if body is None:
        raise ValueError('Truncated message')
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('Expected object')
    return value


class Host:
    def __init__(self, output, core=None):
        self.output = output
        self.core = core or Core(data=DATA / 'extension', port=EXTENSION_PORT)
        self.lock = threading.RLock()
        self.output_lock = threading.Lock()
        self.nodes = []
        self.connected = False
        self.selected = None
        self.address = None
        self.routing_mode = DEFAULT_MODE
        self.closed = threading.Event()

    def send(self, message):
        encoded = json.dumps(message, ensure_ascii=False).encode('utf-8')
        if len(encoded) > 1024 * 1024:
            raise ValueError('Response too large')
        with self.output_lock:
            self.output.write(struct.pack('<I', len(encoded)) + encoded)
            self.output.flush()

    def status(self):
        return {'connected': self.connected and self.core.alive(), 'port': EXTENSION_PORT,
                'ip': self.address, 'selected': self.selected, 'routingMode': self.routing_mode,
                'nodes': [{'index': i, 'name': n['name'], 'protocol': n['outbound']['type']}
                          for i, n in enumerate(self.nodes)]}

    def dispatch(self, request):
        action = request.get('action')
        with self.lock:
            if action == 'checkUpdate':
                return check_update(request.get('version'))
            if action == 'installUpdate':
                if self.connected:
                    raise RuntimeError('Отключите VPN перед обновлением.')
                return launch_update()
            if action == 'status':
                return self.status()
            if action == 'load':
                if self.connected:
                    raise RuntimeError('Сначала отключите VPN.')
                value = request.get('subscription')
                if not isinstance(value, str) or not 0 < len(value) <= MAX_MESSAGE:
                    raise RuntimeError('Вставьте ссылку подписки.')
                nodes, skipped = fetch_subscription(value)
                if len(nodes) > 500:
                    raise RuntimeError('Слишком много подключений (максимум 500).')
                self.nodes = nodes
                self.selected = 0
                return {**self.status(), 'skipped': len(skipped)}
            if action == 'connect':
                index = request.get('index')
                mode = request.get('routing_mode', DEFAULT_MODE)
                if mode not in MODES:
                    raise RuntimeError('Неизвестный режим маршрутизации.')
                if type(index) is not int or not 0 <= index < len(self.nodes):
                    raise RuntimeError('Загрузите подписку и выберите подключение.')
                self.connected = False
                self.address = None
                try:
                    self.core.start(self.nodes[index], mode)
                    try:
                        self.address = check_connection(EXTENSION_PORT)
                    except Exception as error:
                        protocol = 'VLESS/sing-box' if self.nodes[index]['outbound']['type'] == 'vless' else 'Hysteria 2/sing-box'
                        reason = str(error) if isinstance(error, ConnectionCheckError) else 'Не удалось проверить интернет через сервер.'
                        hint = self.core.connection_hint()
                        if not isinstance(hint, str):
                            hint = ''
                        route = 'Россия напрямую' if mode == 'ru-direct' else 'Всё через VPN'
                        raise RuntimeError(f'{protocol}, {route}: {reason} {hint}'.strip()) from None
                    self.connected = True
                    self.routing_mode = mode
                    self.selected = index
                    return self.status()
                except Exception:
                    self.core.stop()
                    raise
            if action == 'disconnect':
                self.connected = False
                self.address = None
                self.core.stop()
                return self.status()
            raise RuntimeError('Неизвестная команда.')

    def monitor(self):
        while not self.closed.wait(1):
            with self.lock:
                if self.connected and not self.core.alive():
                    self.connected = False
                    self.address = None
                    self.core.stop()
                    try:
                        self.send({'event': 'stopped', 'error': 'Ядро VPN завершилось. Переподключитесь или отключите VPN.'})
                    except (BrokenPipeError, OSError):
                        return

    def run(self, input_stream):
        watcher = threading.Thread(target=self.monitor, daemon=True)
        watcher.start()
        try:
            while True:
                request = read_message(input_stream)
                if request is None:
                    break
                identifier = request.get('id')
                if type(identifier) is not int or not 0 <= identifier <= 2**31 - 1:
                    raise ValueError('Invalid request ID')
                try:
                    value = self.dispatch(request)
                    response = {'id': identifier, 'ok': True, 'result': value}
                except (RuntimeError, SubscriptionError) as exc:
                    response = {'id': identifier, 'ok': False, 'error': str(exc)}
                except Exception:
                    response = {'id': identifier, 'ok': False, 'error': 'Ошибка помощника. Перезапустите расширение.'}
                self.send(response)
        finally:
            self.closed.set()
            with self.lock:
                self.connected = False
                self.core.stop()


def main():
    if os.name != 'nt' or len(sys.argv) < 2 or sys.argv[1] != f'chrome-extension://{EXTENSION_ID}/':
        return 2
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        Host(sys.stdout.buffer).run(sys.stdin.buffer)
        return 0
    except (ValueError, OSError, BrokenPipeError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
