import io
import json
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from native_host import Host, read_message, MAX_MESSAGE
from subscription import parse_link, make_config
from diagnostics import ConnectionCheckError

PASSWORD = 'not-a-real-password'


def frame(message):
    body = json.dumps(message).encode()
    return struct.pack('<I', len(body)) + body


class NativeHostTests(unittest.TestCase):
    def test_probe_stage_and_code_reach_extension_without_private_exception_text(self):
        output, core = io.BytesIO(), Mock()
        core.connection_hint.return_value = 'VPN-сервер отклонил авторизацию. [HYSTERIA_AUTHENTICATION]'
        host = Host(output, core=core)
        host.nodes = [parse_link(f'hy2://{PASSWORD}@127.0.0.1:443?sni=localhost')]
        error = ConnectionCheckError('Не получен ответ. [SOCKS_CONNECT_TIMEOUT]',
                                     code='SOCKS_CONNECT_TIMEOUT', stage='SOCKS_CONNECT')
        with patch('native_host.check_connection', side_effect=error):
            host.run(io.BytesIO(frame({'id': 1, 'action': 'connect', 'index': 0})))
        output.seek(0)
        message = read_message(output)
        self.assertFalse(message['ok'])
        self.assertEqual(message['errorCode'], 'SOCKS_CONNECT_TIMEOUT')
        self.assertEqual(message['errorStage'], 'SOCKS_CONNECT')
        self.assertIn('[HYSTERIA_AUTHENTICATION]', message['error'])
        self.assertNotIn(PASSWORD, json.dumps(message))

    def test_frames_and_truncation(self):
        data = io.BytesIO(frame({'id': 1}) + frame({'id': 2}))
        self.assertEqual(read_message(data), {'id': 1})
        self.assertEqual(read_message(data), {'id': 2})
        self.assertIsNone(read_message(data))
        for payload in (b'\x01', struct.pack('<I', 9) + b'{}', struct.pack('<I', MAX_MESSAGE + 1)):
            with self.assertRaises(ValueError):
                read_message(io.BytesIO(payload))

    def test_eof_stops_core_and_unknown_command(self):
        output, core = io.BytesIO(), Mock()
        host = Host(output, core=core)
        host.run(io.BytesIO(frame({'id': 1, 'action': 'shell', 'cmd': 'not executable'})))
        output.seek(0)
        self.assertFalse(read_message(output)['ok'])
        core.start.assert_not_called()
        core.stop.assert_called_once()

    def test_only_summaries_leave_host(self):
        host = Host(io.BytesIO(), core=Mock())
        secret = f'hysteria2://{PASSWORD}@127.0.0.1:443?sni=localhost#Demo'
        with patch('native_host.fetch_subscription', return_value=([parse_link(secret)], [])):
            result = host.dispatch({'action': 'load', 'subscription': secret})
        self.assertEqual(result['nodes'][0]['protocol'], 'hysteria2')
        self.assertNotIn(PASSWORD, json.dumps(result))
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': True})
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': 10})

    def test_connect_failure_stops_core(self):
        core = Mock()
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link(f'hysteria2://{PASSWORD}@127.0.0.1:443?sni=localhost')]
        with patch('native_host.check_connection', side_effect=OSError('private URL here')):
            with self.assertRaisesRegex(RuntimeError, 'проверить интернет'):
                host.dispatch({'action': 'connect', 'index': 0})
        core.stop.assert_called_once()
        self.assertFalse(host.connected)

    def test_routing_mode_reaches_core_and_invalid_mode_is_rejected(self):
        core = Mock(port=24321)
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link(f'hysteria2://{PASSWORD}@127.0.0.1:443?sni=localhost')]
        with patch('native_host.check_connection', return_value='1.2.3.4'):
            for mode in ('ru-direct', 'all'):
                result = host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': mode})
                core.start.assert_called_with(host.nodes[0], mode)
                self.assertEqual(result['routingMode'], mode)
        core.start.reset_mock()
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': 'invalid'})
        core.start.assert_not_called()

    def test_actual_core_port_reaches_probe_and_status_and_is_cleared_on_disconnect(self):
        core = Mock(port=24567)
        host = Host(io.BytesIO(), core=core)
        self.assertIsNone(host.status()['port'])
        host.nodes = [parse_link(f'hy2://{PASSWORD}@127.0.0.1:443?sni=localhost')]
        with patch('native_host.check_connection', return_value='203.0.113.2') as probe:
            result = host.dispatch({'action': 'connect', 'index': 0})
        probe.assert_called_once_with(24567)
        self.assertEqual(result['port'], 24567)
        core.port = 25678
        self.assertEqual(host.status()['port'], 25678)
        core.alive.return_value = False
        self.assertIsNone(host.status()['port'])
        core.alive.return_value = True
        self.assertIsNone(host.dispatch({'action': 'disconnect'})['port'])

    def test_production_host_requests_an_os_allocated_port(self):
        host = Host(io.BytesIO())
        self.assertEqual(host.core.requested_port, 0)
        self.assertIsNone(host.status()['port'])

    def test_hysteria_config_preserves_tls(self):
        node = parse_link('hy2://secret@example.org:443?sni=example.net&obfs=salamander&obfs-password=abc')
        config = make_config(node, 17891, 'all')
        outbound = config['outbounds'][0]
        self.assertEqual(outbound['tls']['server_name'], 'example.net')
        self.assertTrue(outbound['tls']['enabled'])
        self.assertEqual(outbound['obfs'], {'type': 'salamander', 'password': 'abc'})
        self.assertEqual([out['type'] for out in config['outbounds']], ['hysteria2'])
        self.assertEqual(config['inbounds'][0]['listen'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
