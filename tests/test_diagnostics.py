import io
import unittest
from unittest.mock import Mock, patch

import requests

from diagnostics import CoreDiagnostics, ConnectionCheckError, check_error_message
from native_host import Host
from subscription import parse_link


class DiagnosticsTests(unittest.TestCase):
    def test_only_our_tcp_listener_announcement_supplies_a_port(self):
        diagnostics = CoreDiagnostics()
        for line in ('inbound/mixed[other]: tcp server started at 127.0.0.1:24567',
                     'inbound/mixed[browser]: udp server started at 127.0.0.1:24567',
                     'inbound/mixed[browser]: tcp server started at 0.0.0.0:24567',
                     'inbound/mixed[browser]: tcp server started at 127.0.0.1:0',
                     'inbound/mixed[browser]: tcp server started at 127.0.0.1:70000'):
            diagnostics.record(line)
        self.assertIsNone(diagnostics.listener_port())
        diagnostics.record('\x1b[32mINFO[0000]\x1b[0m inbound/mixed[browser]: tcp server started at 127.0.0.1:24567\n')
        self.assertEqual(diagnostics.listener_port(), 24567)
        diagnostics.record('inbound/mixed[browser]: tcp server started at 127.0.0.1:25678')
        self.assertEqual(diagnostics.listener_port(), 24567)
        self.assertEqual(diagnostics.hint(), '')

    def test_core_output_keeps_only_fixed_categories(self):
        diagnostics = CoreDiagnostics()
        diagnostics.consume(io.BytesIO(b'x509: certificate verification failed for SECRET-HOST SECRET-UUID\n'))
        self.assertIn('[SERVER_CERTIFICATE]', diagnostics.hint())
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

    def test_quic_authentication_dns_and_network_errors_remain_specific(self):
        cases = [('CRYPTO_ERROR 0x128 (remote): tls: handshake failure SECRET', 'QUIC_TLS_HANDSHAKE'),
                 ('authentication failed: SECRET HTTP 403', 'HYSTERIA_AUTHENTICATION'),
                 ('lookup SECRET: no such host', 'DNS_LOOKUP'),
                 ('connectex: forbidden by its access permissions SECRET', 'OS_NETWORK_PERMISSION'),
                 ('timeout: no recent network activity SECRET', 'NETWORK_TIMEOUT')]
        for line, code in cases:
            with self.subTest(code=code):
                diagnostics = CoreDiagnostics()
                diagnostics.record(line)
                self.assertIn('[' + code + ']', diagnostics.hint())
                self.assertNotIn('SECRET', diagnostics.hint())
                diagnostics.record('context deadline exceeded SECRET')
                self.assertIn('[' + code + ']', diagnostics.hint())

    def test_requests_connect_and_read_timeouts_are_distinct(self):
        self.assertIn('[CONNECT_TIMEOUT]', check_error_message(requests.exceptions.ConnectTimeout('SECRET')))
        self.assertIn('[HTTP_TIMEOUT]', check_error_message(requests.exceptions.ReadTimeout('SECRET')))

    def test_host_reports_protocol_route_and_safe_core_hint(self):
        core = Mock()
        core.connection_hint.return_value = 'TCP connection refused.'
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link('hy2://secret@127.0.0.1:443?sni=localhost')]
        with patch('native_host.check_connection', side_effect=ConnectionCheckError('SOCKS5 probe failed.')):
            with self.assertRaisesRegex(RuntimeError, '(?s)Hysteria 2/sing-box.*SOCKS5.*TCP connection refused'):
                host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': 'all'})
        core.stop.assert_called_once()
        self.assertFalse(host.connected)


if __name__ == '__main__':
    unittest.main()
