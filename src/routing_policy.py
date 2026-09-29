"""Split-tunnel rules for Hysteria 2 on sing-box."""
import hashlib
import ipaddress
import json
from pathlib import Path
import sys
import re

DEFAULT_MODE = 'ru-direct'
MODES = ('ru-direct', 'all')
ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_policy():
    try:
        encoded = (ROOT / 'routing/ru-direct.json').read_bytes()
        metadata = json.loads((ROOT / 'routing/SOURCES.json').read_text(encoding='utf-8'))
        if hashlib.sha256(encoded).hexdigest() != metadata['policy_sha256']:
            raise ValueError('Hash mismatch')
        policy = json.loads(encoded)
        for key in ('domain', 'domain_suffix', 'domain_regex', 'domain_keyword', 'ip_cidr'):
            if not isinstance(policy[key], list):
                raise ValueError('Invalid policy')
        return policy
    except (OSError, ValueError, KeyError):
        raise RuntimeError('Не удалось прочитать правила маршрутизации. Распакуйте полный комплект программы или выберите «Всё через VPN».') from None


def check_mode(mode):
    if mode not in MODES:
        raise ValueError('Unknown routing mode')


def default_rules():
    path = ROOT / 'routing/default-rules.json' if getattr(sys, 'frozen', False) else ROOT.parent / 'extension/routing-defaults.json'
    return json.loads(path.read_text(encoding='utf-8'))


def validate_rules(rules):
    if not isinstance(rules, list) or len(rules) > 500:
        raise RuntimeError('Допустимо не более 500 правил маршрутизации.')
    result = []
    for index, rule in enumerate(rules, 1):
        try:
            if not isinstance(rule, dict) or set(rule) != {'type', 'value', 'outbound', 'enabled'}:
                raise ValueError()
            kind, value = rule['type'], rule['value']
            if rule['outbound'] not in ('vpn', 'direct') or type(rule['enabled']) is not bool:
                raise ValueError()
            if not isinstance(value, str) or len(value) > 253:
                raise ValueError()
            value = value.strip()
            if kind == 'domain':
                value = value.removeprefix('*.').lstrip('.').rstrip('.').encode('idna').decode('ascii').lower()
                if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
                    raise ValueError()
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    pass
                else:
                    raise ValueError()
            elif kind == 'ip':
                if '%' in value:
                    raise ValueError()
                value = str(ipaddress.ip_network(value, strict=False))
            elif kind == 'geoip-ru':
                if value:
                    raise ValueError()
            else:
                raise ValueError()
            result.append({'type': kind, 'value': value, 'outbound': rule['outbound'], 'enabled': rule['enabled']})
        except (ValueError, TypeError, UnicodeError):
            raise RuntimeError(f'Правило {index}: проверьте тип, домен/IP и маршрут. Указывайте домен без https://, пути и порта; IP — отдельно или в формате CIDR.') from None
    return result


def apply_singbox(config, mode=DEFAULT_MODE, routing_rules=None):
    check_mode(mode)
    if mode == 'all':
        return config
    entries = validate_rules(default_rules() if routing_rules is None else routing_rules)
    config['outbounds'].append({'type': 'direct', 'tag': 'direct', 'domain_resolver': 'bootstrap'})
    # Preserve unknown hostnames for resolution by the VPN server, as in all mode.
    # IP rules apply to literal destinations; do not add a DNS dependency to VPN traffic.
    rules = []
    for entry in entries:
        if not entry['enabled']:
            continue
        if entry['type'] == 'domain':
            match = {'domain_suffix': [entry['value']]}
        elif entry['type'] == 'ip':
            match = {'ip_cidr': [entry['value']]}
        else:
            match = {'ip_cidr': load_policy()['ip_cidr']}
            if not match['ip_cidr']:
                raise RuntimeError('Список IP России пуст. Переустановите комплект.')
        rules.append({**match, 'action': 'route', 'outbound': entry['outbound']})
    config['route']['rules'] = rules
    return config
