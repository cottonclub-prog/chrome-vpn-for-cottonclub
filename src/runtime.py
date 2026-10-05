"""User-mode core lifecycle and an isolated Chrome profile (Windows)."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading

from subscription import make_config
from diagnostics import CoreDiagnostics, ConnectionCheckError, check_error_message
from app_paths import APP_DIRECTORY

PORT = 17890
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA = APP_DIRECTORY


class KillOnCloseJob:
    """Windows closes the core too if the GUI crashes or is terminated."""
    def __init__(self):
        class BASIC(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                        ('MaxWorkingSet', ctypes.c_size_t), ('ActiveLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD),
                        ('Scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('Basic', BASIC), ('Io', IO), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t),
                        ('PeakJob', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = EXTENDED()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise RuntimeError('Не удалось настроить завершение VPN вместе с программой.')

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            raise RuntimeError('Windows не разрешила управление процессом VPN.')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def chrome_path():
    for base in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
        if base:
            path = Path(base) / 'Google/Chrome/Application/chrome.exe'
            if path.is_file():
                return path
    raise RuntimeError('Chrome не найден. Установите Google Chrome для текущего пользователя.')


def chrome_args(executable, data=DATA, port=PORT):
    return [str(executable), f'--user-data-dir={data / "chrome-profile"}',
            f'--proxy-server=socks5://127.0.0.1:{port}',
            '--proxy-bypass-list=<-loopback>',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
            '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
            '--disable-quic', '--no-first-run', '--no-default-browser-check',
            '--new-window', 'https://api.ipify.org/']


class Core:
    def __init__(self, binary=None, data=DATA, port=PORT):
        self.binary = Path(binary or ROOT / 'bin/sing-box.exe')
        self.data, self.port = Path(data), port
        self.process = None
        self.job = None
        self.config_path = None
        self.diagnostics = CoreDiagnostics()
        self.log_thread = None

    def start(self, node, routing_mode='ru-direct', routing_rules=None):
        self.stop()
        self.diagnostics = CoreDiagnostics()
        if not self.binary.is_file():
            raise RuntimeError(f'Нет bin/{self.binary.name}. Распакуйте полный архив программы.')
        # Refuse an occupied port, never switch Chrome onto an unrelated local proxy.
        try:
            with socket.socket() as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', self.port))
        except OSError:
            raise RuntimeError(f'Порт {self.port} занят. Закройте другую копию программы.') from None
        self.data.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='core-',
                                             dir=self.data, encoding='utf-8', delete=False) as f:
                self.config_path = Path(f.name)
                json.dump(make_config(node, self.port, routing_mode, routing_rules), f)
            checked = subprocess.run([str(self.binary), 'check', '-c', str(self.config_path)],
                                     capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
            if checked.returncode:
                raise RuntimeError('Ядро отклонило конфигурацию. Параметры этой ссылки пока не поддерживаются.')
            if os.name == 'nt':
                self.job = KillOnCloseJob()
            self.process = subprocess.Popen([str(self.binary), 'run', '-c', str(self.config_path)],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
            self.log_thread = threading.Thread(target=self.diagnostics.consume,
                                               args=(self.process.stdout,), daemon=True)
            self.log_thread.start()
            if self.job:
                self.job.assign(self.process)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Ядро VPN завершилось при запуске. Проверьте параметры подключения.')
                try:
                    with socket.create_connection(('127.0.0.1', self.port), timeout=.3) as s:
                        s.sendall(b'\x05\x01\x00')
                        if s.recv(2) == b'\x05\x00':
                            # Core has consumed the config; don't retain credentials on disk.
                            self.config_path.unlink(missing_ok=True)
                            self.config_path = None
                            return
                except OSError:
                    pass
                time.sleep(.1)
            raise RuntimeError('Локальный прокси не запустился за 10 секунд.')
        except Exception:
            self.stop()
            raise

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def connection_hint(self):
        return self.diagnostics.hint()

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=4)
            self.process = None
        if self.log_thread:
            self.log_thread.join(timeout=1)
            self.log_thread = None
        if self.job:
            self.job.close()
            self.job = None
        if self.config_path:
            self.config_path.unlink(missing_ok=True)
            self.config_path = None


def check_connection(port=PORT):
    # requests must use the local proxy explicitly, with no direct fallback.
    import requests
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get('https://api.ipify.org',
                                   proxies={'https': f'socks5h://127.0.0.1:{port}'}, timeout=(8, 15))
            response.raise_for_status()
            import ipaddress
            return str(ipaddress.ip_address(response.text.strip()))
        except (requests.RequestException, ValueError) as error:
            raise ConnectionCheckError(check_error_message(error)) from None
