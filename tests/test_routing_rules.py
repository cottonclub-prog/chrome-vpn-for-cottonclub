import ipaddress
import io
import unittest
from unittest.mock import Mock, patch

from native_host import Host
from routing_policy import default_rules, load_policy, validate_rules
from subscription import make_config, parse_link


def rule(kind, value, outbound='direct', enabled=True):
    return {'type': kind, 'value': value, 'outbound': outbound, 'enabled': enabled}


class RoutingRuleTests(unittest.TestCase):
    def test_defaults_only_contain_requested_groups_and_no_private_ranges(self):
        self.assertEqual(default_rules(), [rule('geoip-ru', ''), rule('domain', 'ru'),
                                          rule('domain', 'su'), rule('domain', 'xn--p1ai')])
        policy = load_policy()
        self.assertTrue(policy['ip_cidr'])
        self.assertTrue(all(ipaddress.ip_network(value).is_global for value in policy['ip_cidr']))
        for key in ('domain', 'domain_suffix', 'domain_regex', 'domain_keyword'):
            self.assertFalse(policy[key])

    def test_domains_idn_and_ip_networks_are_normalized(self):
        entries = validate_rules([rule('domain', '*.Example.COM.'), rule('domain', '.рф'),
                                 rule('ip', '192.168.1.20/24'), rule('ip', '2001:db8::1')])
        self.assertEqual([r['value'] for r in entries], ['example.com', 'xn--p1ai', '192.168.1.0/24', '2001:db8::1/128'])

    def test_invalid_rules_are_rejected_including_disabled_ones(self):
        invalid = [None, {}, [rule('domain', '')], [rule('domain', 'https://example.com')],
                   [rule('domain', 'example.com/path')], [rule('domain', 'example.com:443')],
                   [rule('domain', '127.0.0.1')], [rule('ip', '1.2.3.999')],
                   [rule('ip', '192.168.0.1/99')], [rule('ip', 'fe80::1%eth0')],
                   [rule('regex', '.*')], [rule('geoip-ru', 'wrong')],
                   [rule('domain', 'example.com', 'invalid')], [rule('domain', 'x', enabled=1)],
                   [rule('domain', '', enabled=False)], [dict(rule('domain', 'x'), action='hijack-dns')],
                   [rule('domain', 'x')] * 501]
        for entries in invalid:
            with self.subTest(entries=str(entries)[:80]), self.assertRaises(RuntimeError):
                validate_rules(entries)

    def test_empty_rules_and_all_mode_do_not_add_direct_catchall(self):
        node = parse_link('hy2://test@127.0.0.1:443?sni=localhost')
        config = make_config(node, 17890, 'ru-direct', [])
        self.assertEqual(config['route'], {'final': 'vpn', 'rules': []})
        config = make_config(node, 17890, 'all', [rule('ip', '0.0.0.0/0')])
        self.assertEqual(config['route'], {'final': 'vpn'})

    def test_native_host_validates_and_passes_rules_without_exposing_config(self):
        core = Mock()
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link('hy2://test@127.0.0.1:443?sni=localhost')]
        entries = [rule('domain', '.рф', 'vpn'), rule('ip', '192.168.1.20')]
        expected = validate_rules(entries)
        self.assertEqual(host.dispatch({'action': 'validateRouting', 'rules': entries}), {'rules': expected})
        with patch('native_host.check_connection', return_value='1.2.3.4'):
            host.dispatch({'action': 'connect', 'index': 0, 'routing_rules': entries})
        core.start.assert_called_once_with(host.nodes[0], 'ru-direct', expected)
        core.start.reset_mock()
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': 0, 'routing_rules': [rule('ip', 'invalid')]})
        core.start.assert_not_called()
