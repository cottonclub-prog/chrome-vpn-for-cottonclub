"""Split-tunnel rules for Hysteria 2 on sing-box."""
import copy
import hashlib
import json
from pathlib import Path
import sys

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


def domain_rule(policy):
    return {key: policy[key] for key in ('domain', 'domain_suffix', 'domain_regex', 'domain_keyword') if policy[key]}


def apply_singbox(config, mode=DEFAULT_MODE, policy=None):
    check_mode(mode)
    if mode == 'all':
        return config
    policy = copy.deepcopy(policy) if policy is not None else load_policy()
    config['outbounds'].append({'type': 'direct', 'tag': 'direct', 'domain_resolver': 'bootstrap'})
    # Preserve unknown hostnames for resolution by the VPN server, as in all mode.
    # IP rules apply to literal destinations; do not add a DNS dependency to VPN traffic.
    rules = []
    domains = domain_rule(policy)
    if domains:
        rules.append({**domains, 'action': 'route', 'outbound': 'direct'})
    if policy['ip_cidr']:
        rules.append({'ip_cidr': policy['ip_cidr'], 'action': 'route', 'outbound': 'direct'})
    config['route']['rules'] = rules
    return config
