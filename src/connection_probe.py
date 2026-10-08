"""Bounded SOCKS5, TLS and HTTPS checks, with no direct network fallback."""
import http.client
import ipaddress
import socket
import ssl
import threading
import time

import certifi

from diagnostics import ConnectionCheckError


CHECK_HOST = 'api.ipify.org'
CHECK_PORT = 443
TOTAL_TIMEOUT = 30
STAGE_TIMEOUTS = {'LOCAL_PROXY': 2, 'SOCKS_GREETING': 2, 'SOCKS_CONNECT': 8,
                  'HTTPS_TLS': 8, 'HTTP_HEADERS': 15, 'HTTP_BODY': 15}


def failure(code, stage, message):
    return ConnectionCheckError(f'{message} [{code}]', code=code, stage=stage)


def remaining(sock, deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError()
    sock.settimeout(seconds)


def read_exact(sock, count, deadline):
    data = bytearray()
    while len(data) < count:
        remaining(sock, deadline)
        part = sock.recv(count - len(data))
        if not part:
            raise EOFError()
        data.extend(part)
    return bytes(data)


def timeout_failure(stage):
    messages = {
        'LOCAL_PROXY': 'Локальный прокси не ответил на TCP-подключение.',
        'SOCKS_GREETING': 'Локальный прокси не ответил на приветствие SOCKS5.',
        'SOCKS_CONNECT': 'За 8 секунд прокси не подтвердил соединение через VPN. HTTPS ещё не начался; точная причина требует ответа ядра.',
        'HTTPS_TLS': 'Соединение через VPN подтверждено, но TLS HTTPS-сервиса проверки IP не завершился вовремя.',
        'HTTP_HEADERS': 'TLS HTTPS-сервиса установлен, но HTTP-ответ проверки IP не получен вовремя.',
        'HTTP_BODY': 'HTTPS-сервис ответил, но передача IP-адреса не завершилась вовремя.',
    }
    return failure(stage + '_TIMEOUT', stage, messages[stage])


def check_connection(port):
    """Return a validated IP, or a fixed error tied to the observed failure stage."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise failure('LOCAL_PROXY_PORT', 'LOCAL_PROXY', 'Помощник передал неверный порт локального прокси.')
    stage = 'LOCAL_PROXY'
    sock = tls = response = None
    watchdog = None
    http_expired = threading.Event()
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        # Only this loopback TCP address is dialled. The destination name is sent
        # to SOCKS5; neither system proxies nor local destination DNS are used.
        sock = socket.create_connection(('127.0.0.1', port), timeout=STAGE_TIMEOUTS[stage])
        stage = 'SOCKS_GREETING'
        limit = min(deadline, time.monotonic() + STAGE_TIMEOUTS[stage])
        remaining(sock, limit)
        sock.sendall(b'\x05\x01\x00')
        if read_exact(sock, 2, limit) != b'\x05\x00':
            raise failure('SOCKS_GREETING_INVALID', stage, 'Локальный прокси не подтвердил SOCKS5 без авторизации.')

        stage = 'SOCKS_CONNECT'
        limit = min(deadline, time.monotonic() + STAGE_TIMEOUTS[stage])
        name = CHECK_HOST.encode('idna')
        remaining(sock, limit)
        sock.sendall(b'\x05\x01\x00\x03' + bytes([len(name)]) + name + CHECK_PORT.to_bytes(2, 'big'))
        header = read_exact(sock, 4, limit)
        if header[0] != 5 or header[2] != 0:
            raise failure('SOCKS_REPLY_INVALID', stage, 'Локальный прокси вернул некорректный ответ SOCKS5.')
        if header[1]:
            details = {1: 'общий отказ', 2: 'запрет правилами', 3: 'сеть недоступна',
                       4: 'узел недоступен', 5: 'соединение отклонено', 6: 'истёк TTL',
                       7: 'команда не поддерживается', 8: 'тип адреса не поддерживается'}
            detail = details.get(header[1], 'неизвестный отказ')
            raise failure(f'SOCKS_REPLY_{header[1]}', stage,
                          f'Прокси не открыл соединение к HTTPS-сервису через VPN: {detail}.')
        lengths = {1: 4, 4: 16}
        length = read_exact(sock, 1, limit)[0] if header[3] == 3 else lengths.get(header[3])
        if not length:
            raise failure('SOCKS_REPLY_INVALID', stage, 'Локальный прокси вернул неверный тип адреса SOCKS5.')
        read_exact(sock, length + 2, limit)

        stage = 'HTTPS_TLS'
        limit = min(deadline, time.monotonic() + STAGE_TIMEOUTS[stage])
        context = ssl.create_default_context(cafile=certifi.where())
        remaining(sock, limit)
        tls = context.wrap_socket(sock, server_hostname=CHECK_HOST, do_handshake_on_connect=False)
        remaining(tls, limit)
        tls.do_handshake()

        stage = 'HTTP_HEADERS'
        # Headers and body share one deadline, so fragmented or trickling
        # responses cannot extend this check indefinitely.
        limit = min(deadline, time.monotonic() + STAGE_TIMEOUTS[stage])
        remaining(tls, limit)
        def expire_http():
            http_expired.set()
            try:
                tls.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        watchdog = threading.Timer(max(0, limit - time.monotonic()), expire_http)
        watchdog.daemon = True
        watchdog.start()
        tls.sendall(b'GET / HTTP/1.1\r\nHost: api.ipify.org\r\nConnection: close\r\n'
                    b'User-Agent: CottonClubVPN-ConnectionCheck\r\n\r\n')
        response = http.client.HTTPResponse(tls)
        remaining(tls, limit)
        response.begin()
        if response.status != 200:
            raise failure('HTTP_STATUS', stage, f'HTTPS-сервис проверки IP вернул HTTP {response.status}.')
        stage = 'HTTP_BODY'
        remaining(tls, limit)
        body = response.read(1025)
        remaining(tls, limit)
        if http_expired.is_set():
            raise TimeoutError()
        if len(body) > 1024:
            raise ValueError()
        if response.length not in (None, 0):
            raise failure('HTTP_INCOMPLETE', stage, 'HTTPS-сервис оборвал передачу ответа проверки IP.')
        return str(ipaddress.ip_address(body.decode('ascii').strip()))
    except ConnectionCheckError:
        raise
    except ssl.SSLCertVerificationError:
        raise failure('HTTPS_CERTIFICATE', stage,
                      'Сертификат HTTPS-сервиса проверки IP не прошёл проверку внутри туннеля. Проверьте дату Windows и HTTPS-фильтрацию антивируса.') from None
    except TimeoutError:
        raise timeout_failure(stage) from None
    except ssl.SSLError:
        if http_expired.is_set():
            raise timeout_failure(stage) from None
        raise failure('HTTPS_TLS_ERROR', stage, 'Ошибка TLS-соединения с HTTPS-сервисом проверки IP внутри туннеля.') from None
    except PermissionError:
        raise failure('OS_NETWORK_PERMISSION', stage, 'Windows запретила сетевую операцию проверки подключения. Проверьте правила защиты.') from None
    except ConnectionRefusedError:
        message = ('Соединение с локальным прокси отклонено; проверьте, запущено ли ядро VPN.' if stage == 'LOCAL_PROXY'
                   else 'Соединение отклонено на этапе ' + stage + '.')
        raise failure(stage + '_REFUSED', stage, message) from None
    except (EOFError, OSError, http.client.HTTPException):
        if http_expired.is_set():
            raise timeout_failure(stage) from None
        raise failure(stage + '_CLOSED', stage, 'Соединение оборвалось на этапе ' + stage + '. Повторите подключение и проверьте сообщение ядра.') from None
    except (ValueError, UnicodeError):
        raise failure('HTTP_INVALID_IP', stage, 'HTTPS-сервис проверки вернул ответ, который не является IP-адресом.') from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
            watchdog.join()
        if response is not None:
            response.close()
        if tls is not None:
            tls.close()
        if sock is not None:
            sock.close()
