import io
import json
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from native_host import Host, read_message, MAX_MESSAGE
from subscription import parse_link
from xray_config import make_xray_config

UUID = '11111111-1111-4111-8111-111111111111'


def frame(message):
    body = json.dumps(message).encode()
    return struct.pack('<I', len(body)) + body


class NativeHostTests(unittest.TestCase):
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
        secret = f'vless://{UUID}@127.0.0.1:443?security=none#Demo'
        with patch('native_host.fetch_subscription', return_value=([parse_link(secret)], [])):
            result = host.dispatch({'action': 'load', 'subscription': secret})
        self.assertEqual(result['nodes'][0]['protocol'], 'vless')
        self.assertNotIn(UUID, json.dumps(result))
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': True})
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': 10})

    def test_connect_failure_stops_core(self):
        core = Mock()
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link(f'vless://{UUID}@127.0.0.1:443?security=none')]
        with patch('native_host.check_connection', side_effect=OSError('private URL here')):
            with self.assertRaisesRegex(RuntimeError, 'проверить интернет'):
                host.dispatch({'action': 'connect', 'index': 0})
        core.stop.assert_called_once()
        self.assertFalse(host.connected)

    def test_routing_mode_reaches_core_and_invalid_mode_is_rejected(self):
        core = Mock()
        host = Host(io.BytesIO(), core=core)
        host.nodes = [parse_link(f'vless://{UUID}@127.0.0.1:443?security=none')]
        with patch('native_host.check_connection', return_value='1.2.3.4'):
            for mode in ('ru-direct', 'all'):
                result = host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': mode})
                core.start.assert_called_with(host.nodes[0], mode)
                self.assertEqual(result['routingMode'], mode)
        core.start.reset_mock()
        with self.assertRaises(RuntimeError):
            host.dispatch({'action': 'connect', 'index': 0, 'routing_mode': 'invalid'})
        core.start.assert_not_called()

    def test_xray_reality_adapter(self):
        node = parse_link(f'vless://{UUID}@example.org:443?security=reality&pbk=public&sid=abcd&sni=example.net&fp=chrome&flow=xtls-rprx-vision')
        config = make_xray_config(node, 17891, 'all')
        reality = config['outbounds'][0]['streamSettings']['realitySettings']
        self.assertEqual(reality['password'], 'public')
        self.assertEqual(reality['serverName'], 'example.net')
        self.assertEqual([out['protocol'] for out in config['outbounds']], ['vless'])
        self.assertEqual(config['inbounds'][0]['listen'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
