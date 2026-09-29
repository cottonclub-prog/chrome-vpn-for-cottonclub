import io
import unittest
from unittest.mock import Mock, patch

import requests

from diagnostics import CoreDiagnostics, ConnectionCheckError, check_error_message
from native_host import Host
from subscription import parse_link


class DiagnosticsTests(unittest.TestCase):
    def test_core_output_keeps_only_fixed_categories(self):
        diagnostics = CoreDiagnostics()
        diagnostics.consume(io.BytesIO(b'failed REALITY verification for SECRET-HOST SECRET-UUID\n'))
        self.assertIn('Reality', diagnostics.hint())
        self.assertNotIn('SECRET', diagnostics.hint())

    def test_unrecognized_output_is_not_exposed(self):
        diagnostics = CoreDiagnostics()
        diagnostics.record('unknown failure SECRET-SUBSCRIPTION')
        self.assertEqual(diagnostics.hint(), '')

    def test_distinguishes_probe_errors_without_exception_text(self):
        cases = [(requests.exceptions.Timeout('SECRET'), 'ожидания'),
                 (requests.exceptions.SSLError('SECRET'), 'TLS'),
                 (requests.exceptions.ConnectionError('SECRET'), 'SOCKS5'),
                 (ValueError('SECRET'), 'IP-адресом')]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                message = check_error_message(error)
                self.assertIn(expected, message)
                self.assertNotIn('SECRET', message)

    def test_host_reports_protocol_route_and_safe_core_hint(self):
        core = Mock()
        core.connection_hint.return_value = 'TCP connection refused.'
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link('vless://11111111-1111-4111-8111-111111111111@127.0.0.1:443?security=none')]
        with patch('native_host.check_connection', side_effect=ConnectionCheckError('SOCKS5 probe failed.')):
            with self.assertRaisesRegex(RuntimeError, 'VLESS/sing-box.*SOCKS5.*TCP connection refused'):
                host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': 'all'})
        core.stop.assert_called_once()
        self.assertFalse(host.connected)


if __name__ == '__main__':
    unittest.main()
