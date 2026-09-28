"""Keep only fixed error categories; never retain or expose raw core output."""
import threading


class ConnectionCheckError(RuntimeError):
    """An intentionally sanitized explanation suitable for the popup."""


class CoreDiagnostics:
    def __init__(self):
        self._lock = threading.Lock()
        self._hint = ''

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
        text = line.lower()
        hint = ''
        if 'reality' in text and any(token in text for token in ('invalid', 'failed', 'verification', 'mismatch')):
            hint = 'Xray сообщает об ошибке Reality. Проверьте SNI, публичный ключ, shortId и параметры сервера.'
        elif any(token in text for token in ('certificate', 'x509:')) and any(token in text for token in ('failed', 'invalid', 'expired', 'unknown', 'mismatch')):
            hint = 'Ядро сообщает об ошибке сертификата. Проверьте SNI, сертификат сервера и дату Windows.'
        elif any(token in text for token in ('no such host', 'failed to lookup', 'dns lookup failed')):
            hint = 'Ядро не смогло разрешить имя через DNS.'
        elif any(token in text for token in ('connection refused', 'actively refused')):
            hint = 'Ядро получило отказ TCP-соединения. Проверьте доступность сервера и порт.'
        elif any(token in text for token in ('network is unreachable', 'no route to host')):
            hint = 'Ядро сообщает, что сеть назначения недоступна.'
        elif any(token in text for token in ('i/o timeout', 'context deadline exceeded', 'connection timed out')):
            hint = 'Ядро не дождалось ответа сети. Возможны недоступность сервера или фильтрация соединения.'
        if hint:
            with self._lock:
                self._hint = hint

    def hint(self):
        with self._lock:
            return self._hint


def check_error_message(error):
    import requests
    if isinstance(error, requests.exceptions.SSLError):
        return 'Не удалось проверить TLS-сертификат HTTPS-сервиса проверки IP внутри туннеля.'
    if isinstance(error, requests.exceptions.Timeout):
        return 'Истекло время ожидания HTTPS-проверки через туннель.'
    if isinstance(error, requests.exceptions.HTTPError):
        code = getattr(error.response, 'status_code', None)
        suffix = f' (HTTP {code})' if type(code) is int and 100 <= code <= 599 else ''
        return f'Сервис проверки IP вернул ошибку{suffix}.'
    if isinstance(error, requests.exceptions.ConnectionError):
        return 'Не удалось выполнить HTTPS-запрос через локальный SOCKS5-прокси.'
    if isinstance(error, ValueError):
        return 'Сервис проверки вернул ответ, который не является IP-адресом.'
    return 'Проверка HTTPS-соединения через туннель завершилась ошибкой.'
