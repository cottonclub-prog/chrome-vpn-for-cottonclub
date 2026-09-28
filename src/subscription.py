"""Convert share links to a deliberately small, local-only sing-box config."""
import base64
import ipaddress
import socket
import ssl
from urllib.error import HTTPError, URLError
from device_identity import subscription_headers
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_SIZE = 2 * 1024 * 1024


class SubscriptionError(ValueError):
    pass


class SecureRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise SubscriptionError('Подписка перенаправляет на небезопасный HTTP-адрес.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_subscription(value):
    value = value.strip()
    if value.startswith('https://'):
        try:
            # Avoid inheriting a broken system proxy. Subscription stays on this PC.
            opener = build_opener(ProxyHandler({}), HTTPSHandler(), SecureRedirect())
            req = Request(value, headers=subscription_headers())
            with opener.open(req, timeout=20) as response:
                data = response.read(MAX_SIZE + 1)
            if len(data) > MAX_SIZE:
                raise SubscriptionError('Подписка слишком большая (максимум 2 МБ).')
            value = data.decode('utf-8-sig')
        except SubscriptionError:
            raise
        except HTTPError as exc:
            # Never include exception strings: they can contain the secret URL.
            if exc.headers.get('X-Hwid-Not-Supported', '').lower() == 'true':
                message = 'Сервер требует идентификатор устройства, но не принял его. Обновите программу или проверьте настройки панели.'
            elif any(exc.headers.get(key, '').lower() == 'true' for key in
                     ('X-Hwid-Limit-Exceeded', 'X-Hwid-Restricted', 'X-Hwid-Limit-Reached')):
                message = 'Достигнут лимит устройств подписки. Освободите устройство в панели или используйте другую подписку.'
            elif exc.code == 404 and exc.headers.get('X-Hwid-Active', '').lower() == 'true':
                message = 'Сервер отклонил устройство. Проверьте лимит устройств подписки в панели (HTTP 404).'
            elif exc.code == 404:
                message = 'Подписка не найдена (HTTP 404). Проверьте полную ссылку и наличие подписки в панели.'
            elif exc.code in (401, 403):
                message = f'Сервер запретил доступ к подписке (HTTP {exc.code}). Проверьте подписку и ограничения устройств.'
            elif exc.code == 429:
                message = 'Слишком много запросов. Подождите немного и загрузите подписку снова.'
            else:
                message = f'Сервер подписки вернул HTTP {exc.code}. Попробуйте позже.'
            raise SubscriptionError(message) from None
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                message = 'Не удалось проверить TLS-сертификат подписки. Проверьте дату Windows и сертификат сервера.'
            elif isinstance(exc.reason, socket.gaierror):
                message = 'Не удалось найти сервер подписки через DNS. Проверьте адрес и подключение к интернету.'
            elif isinstance(exc.reason, (TimeoutError, socket.timeout)):
                message = 'Сервер подписки не ответил за 20 секунд. Попробуйте снова.'
            else:
                message = 'Не удалось соединиться с сервером подписки. Проверьте интернет и доступность сервера.'
            raise SubscriptionError(message) from None
        except TimeoutError:
            raise SubscriptionError('Сервер подписки не ответил за 20 секунд. Попробуйте снова.') from None
        except UnicodeError:
            raise SubscriptionError('Сервер вернул подписку в неподдерживаемой кодировке.') from None
        except Exception:
            raise SubscriptionError('Не удалось загрузить подписку. Проверьте доступ к интернету и папке данных программы.') from None
    elif value.startswith('http://'):
        raise SubscriptionError('Используйте HTTPS-ссылку подписки.')
    return parse_subscription(value)


def parse_subscription(text):
    text = text.strip().lstrip('\ufeff')
    if len(text.encode('utf-8')) > MAX_SIZE:
        raise SubscriptionError('Подписка слишком большая.')
    first_data_line = next((line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith('#')), '')
    if '://' not in first_data_line or first_data_line.startswith(('<', '{', '[')):
        try:
            compact = ''.join(text.split())
            text = base64.b64decode(compact + '=' * (-len(compact) % 4), altchars=b'-_', validate=True).decode('utf-8-sig')
        except (ValueError, UnicodeError):
            raise SubscriptionError('Ожидается список ссылок VLESS/Hysteria 2 или Base64-подписка. JSON/HTML/Clash пока не поддерживаются.') from None
    nodes, errors = [], []
    for index, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            nodes.append(parse_link(line))
        except (ValueError, KeyError):
            errors.append(index)
    if not nodes:
        raise SubscriptionError('Нет поддерживаемых подключений. Нужны VLESS (TCP/WS/gRPC) или Hysteria 2.')
    return nodes, errors


def parse_link(link):
    parsed = urlsplit(link)
    kind = {'vless': 'vless', 'hysteria2': 'hysteria2', 'hy2': 'hysteria2'}.get(parsed.scheme)
    if not kind or not parsed.hostname or not parsed.username:
        raise SubscriptionError('Некорректная ссылка.')
    q = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    node = {'type': kind, 'tag': 'vpn', 'server': parsed.hostname,
            'server_port': parsed.port if parsed.port is not None else 443}
    if node['server_port'] < 1:
        raise SubscriptionError('Некорректный порт.')
    security = q.get('security', 'none') if kind == 'vless' else 'tls'
    if security not in ('none', 'tls', 'reality'):
        raise SubscriptionError('Неподдерживаемый режим TLS.')
    if any(q.get(k, '').lower() in ('1', 'true') for k in ('insecure', 'allowInsecure')):
        raise SubscriptionError('Ссылки с отключённой проверкой сертификата не поддерживаются.')
    if security != 'none':
        tls = {'enabled': True, 'server_name': q.get('sni') or q.get('peer') or parsed.hostname}
        if q.get('alpn'):
            tls['alpn'] = q['alpn'].split(',')
        if kind == 'vless' and (q.get('fp') or security == 'reality'):
            tls['utls'] = {'enabled': True, 'fingerprint': q.get('fp') or 'chrome'}
        if security == 'reality':
            if not q.get('pbk'):
                raise SubscriptionError('Нет публичного ключа Reality.')
            tls['reality'] = {'enabled': True, 'public_key': q['pbk'], 'short_id': q.get('sid', '')}
        node['tls'] = tls
    if kind == 'vless':
        node['uuid'] = str(uuid.UUID(unquote(parsed.username)))
        if q.get('encryption', 'none') not in ('', 'none'):
            raise SubscriptionError('Этот режим шифрования VLESS пока не поддерживается.')
        if q.get('flow'):
            if q['flow'] != 'xtls-rprx-vision':
                raise SubscriptionError('Неподдерживаемый flow.')
            node['flow'] = q['flow']
        transport = q.get('type', 'tcp')
        if transport in ('tcp', 'raw'):
            if q.get('headerType', 'none') not in ('', 'none'):
                raise SubscriptionError('TCP header не поддерживается.')
        elif transport == 'ws':
            node['transport'] = {'type': 'ws', 'path': q.get('path', '/')}
            if q.get('host'):
                node['transport']['headers'] = {'Host': q['host']}
        elif transport == 'grpc':
            node['transport'] = {'type': 'grpc', 'service_name': q.get('serviceName', '')}
        else:
            raise SubscriptionError('Неподдерживаемый транспорт.')
    else:
        node['password'] = unquote(parsed.netloc.rsplit('@', 1)[0])
        if q.get('obfs'):
            if q['obfs'] != 'salamander' or not q.get('obfs-password'):
                raise SubscriptionError('Неподдерживаемая обфускация.')
            node['obfs'] = {'type': 'salamander', 'password': q['obfs-password']}
        if q.get('mport'):
            node['server_ports'] = q['mport'].replace('-', ':').split(',')
        if q.get('pinSHA256'):
            raise SubscriptionError('Закрепление сертификата pinSHA256 пока не поддерживается.')
    name = unquote(parsed.fragment) or f'{kind.upper()} · {parsed.hostname}'
    name = ''.join(c for c in name if c.isprintable())[:120]
    return {'name': name, 'outbound': node}


def make_config(node, port, routing_mode='ru-direct'):
    from routing_policy import apply_singbox
    outbound = dict(node['outbound'])
    try:
        ipaddress.ip_address(outbound['server'])
    except ValueError:
        outbound['domain_resolver'] = 'bootstrap'
    config = {
        'log': {'level': 'error', 'timestamp': False},
        'dns': {'servers': [{'type': 'local', 'tag': 'bootstrap'}]},
        'inbounds': [{'type': 'mixed', 'tag': 'browser', 'listen': '127.0.0.1', 'listen_port': port}],
        'outbounds': [outbound],
        'route': {'final': 'vpn'},
    }
    return apply_singbox(config, routing_mode)
