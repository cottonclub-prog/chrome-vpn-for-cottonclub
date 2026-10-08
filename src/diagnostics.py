"""Keep only fixed error categories; never retain or expose raw core output."""
import threading
import re


class ConnectionCheckError(RuntimeError):
    """An intentionally sanitized explanation suitable for the popup."""

    def __init__(self, message, *, code=None, stage=None):
        super().__init__(message)
        self.code = code
        self.stage = stage


class CoreDiagnostics:
    def __init__(self):
        self._lock = threading.Lock()
        self._hint = ''
        self._listener_port = None
        self._priority = 0
        self._recorded = threading.Event()

    def consume(self, stream):
        try:
            while True:
                line = stream.readline(4096)
                if not line:
                    return
                self.record(line.decode('utf-8', errors='replace'))
        except (OSError, ValueError):
            return
        finally:
            stream.close()

    def record(self, line):
        # Read only the endpoint announced by our own core, not a guessed free port.
        plain = re.sub(r'\x1b\[[0-9;]*m', '', line)
        listener = re.search(r'inbound/mixed\[browser\]: tcp server started at 127\.0\.0\.1:([0-9]{1,5})\s*$', plain)
        if listener and 1 <= int(listener[1]) <= 65535:
            with self._lock:
                if self._listener_port is None:
                    self._listener_port = int(listener[1])
        text = plain.lower()
        hint = ''
        priority = 0
        if any(token in text for token in ('certificate', 'x509:')) and any(token in text for token in ('failed', 'invalid', 'expired', 'unknown', 'mismatch')):
            hint = 'Сертификат VPN-сервера не прошёл проверку. Проверьте SNI, сертификат и дату Windows. [SERVER_CERTIFICATE]'
            priority = 100
        elif any(token in text for token in ('authentication failed', 'authentication error', 'auth failed', 'unauthorized')):
            hint = 'VPN-сервер отклонил авторизацию. Проверьте пароль сервера и актуальность подписки. [HYSTERIA_AUTHENTICATION]'
            priority = 100
        elif any(token in text for token in ('handshake failure', 'handshake_failure', 'crypto_error')):
            hint = 'Не удалось согласовать TLS внутри QUIC с VPN-сервером. Возможна несовместимость TLS-параметров клиента и сервера. [QUIC_TLS_HANDSHAKE]'
            priority = 90
        elif any(token in text for token in ('access permissions', 'permission denied', 'access is denied', 'отказано в доступе', 'запрещено правами доступа')):
            hint = 'Операционная система запретила сетевое соединение ядра. Проверьте правила брандмауэра и антивируса для sing-box. [OS_NETWORK_PERMISSION]'
            priority = 100
        elif any(token in text for token in ('no such host', 'failed to lookup', 'dns lookup failed')):
            hint = 'Ядро не смогло разрешить имя через DNS. [DNS_LOOKUP]'
            priority = 80
        elif any(token in text for token in ('connection refused', 'actively refused')):
            hint = 'Ядро получило отказ соединения. Проверьте доступность сервера и порт. [CONNECTION_REFUSED]'
            priority = 50
        elif any(token in text for token in ('network is unreachable', 'no route to host')):
            hint = 'Сеть назначения недоступна для ядра. [NETWORK_UNREACHABLE]'
            priority = 70
        elif any(token in text for token in ('i/o timeout', 'context deadline exceeded', 'connection timed out', 'no recent network activity')):
            hint = 'Ядро не дождалось ответа сети. Это не позволяет отличить фильтрацию UDP, недоступность сервера и неверные параметры маскировки. [NETWORK_TIMEOUT]'
            priority = 20
        if hint:
            with self._lock:
                if priority >= self._priority:
                    self._hint = hint
                    self._priority = priority
                    self._recorded.set()

    def hint(self, wait=0):
        if wait:
            self._recorded.wait(wait)
        with self._lock:
            return self._hint

    def listener_port(self):
        with self._lock:
            return self._listener_port


def check_error_message(error):
    import requests
    if isinstance(error, requests.exceptions.SSLError):
        return 'Не удалось проверить TLS-сертификат HTTPS-сервиса проверки IP внутри туннеля.'
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return 'Истекло время ожидания соединения через SOCKS5 или TLS-подключения к HTTPS-сервису. [CONNECT_TIMEOUT]'
    if isinstance(error, requests.exceptions.ReadTimeout):
        return 'Истекло время ожидания ответа HTTPS-сервиса через туннель. [HTTP_TIMEOUT]'
    if isinstance(error, requests.exceptions.Timeout):
        return 'Истекло время ожидания проверки через туннель. [PROBE_TIMEOUT]'
    if isinstance(error, requests.exceptions.HTTPError):
        code = getattr(error.response, 'status_code', None)
        suffix = f' (HTTP {code})' if type(code) is int and 100 <= code <= 599 else ''
        return f'Сервис проверки IP вернул ошибку{suffix}.'
    if isinstance(error, requests.exceptions.ConnectionError):
        return 'Не удалось выполнить HTTPS-запрос через локальный SOCKS5-прокси.'
    if isinstance(error, ValueError):
        return 'Сервис проверки вернул ответ, который не является IP-адресом.'
    return 'Проверка HTTPS-соединения через туннель завершилась ошибкой.'
