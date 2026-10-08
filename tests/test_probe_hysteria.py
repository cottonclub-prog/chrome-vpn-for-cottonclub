"""The production checker through a real loopback Hysteria2/sing-box tunnel."""
import copy
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import connection_probe as probe
from diagnostics import ConnectionCheckError
from runtime import Core, ROOT, CREATE_NO_WINDOW
from subscription import parse_link


class Origin(BaseHTTPRequestHandler):
    stalled = threading.Event()
    def do_GET(self):
        if self.server.stall:
            self.stalled.wait(2)
            return
        self.send_response(200)
        self.send_header('Content-Length', '12')
        self.end_headers()
        self.wfile.write(b'203.0.113.10\n')

    def log_message(self, *_):
        pass


@unittest.skipUnless((ROOT / 'bin/sing-box.exe').exists(), 'Run prepare.py first')
class HysteriaProbeTests(unittest.TestCase):
    def test_actual_tunnel_success_auth_failure_obfs_timeout_and_https_timeout(self):
        binary = ROOT / 'bin/sing-box.exe'
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            data = Path(directory)
            generated = subprocess.run([str(binary), 'generate', 'tls-keypair', 'localhost'],
                                       capture_output=True, check=True, creationflags=CREATE_NO_WINDOW).stdout.decode()
            cert = generated[generated.index('-----BEGIN CERTIFICATE-----'):generated.index('-----END CERTIFICATE-----') + len('-----END CERTIFICATE-----')]
            key = generated[generated.index('-----BEGIN PRIVATE KEY-----'):generated.index('-----END PRIVATE KEY-----') + len('-----END PRIVATE KEY-----')]
            cert_path, key_path = data / 'cert.pem', data / 'key.pem'
            cert_path.write_text(cert)
            key_path.write_text(key)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
            origin.stall = False
            Origin.stalled.clear()
            origin.socket = context.wrap_socket(origin.socket, server_side=True)
            threading.Thread(target=origin.serve_forever, daemon=True).start()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
                reservation.bind(('127.0.0.1', 0))
                hy2_port = reservation.getsockname()[1]
            config = {
                'log': {'level': 'error'},
                'inbounds': [{'type': 'hysteria2', 'listen': '127.0.0.1', 'listen_port': hy2_port,
                              'users': [{'password': 'SECRET-auth'}],
                              'obfs': {'type': 'salamander', 'password': 'SECRET-obfs'},
                              'tls': {'enabled': True, 'certificate': [cert], 'key': [key]}}],
                'outbounds': [{'type': 'direct'}],
            }
            path = data / 'server.json'
            path.write_text(json.dumps(config))
            server = subprocess.Popen([str(binary), 'run', '-c', str(path)], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            node = parse_link(f'hy2://SECRET-auth@127.0.0.1:{hy2_port}?sni=localhost&obfs=salamander&obfs-password=SECRET-obfs')
            node['outbound']['tls']['certificate'] = [cert]
            core = Core(data=data / 'client')
            try:
                with patch('connection_probe.CHECK_HOST', 'localhost'), patch('connection_probe.CHECK_PORT', origin.server_port), \
                     patch('connection_probe.certifi.where', return_value=str(cert_path)):
                    core.start(node, 'all')
                    self.assertEqual(probe.check_connection(core.port), '203.0.113.10')
                    origin.stall = True
                    with patch.dict(probe.STAGE_TIMEOUTS, {'HTTP_HEADERS': .5}):
                        with self.assertRaises(ConnectionCheckError) as caught:
                            probe.check_connection(core.port)
                    self.assertEqual(caught.exception.code, 'HTTP_HEADERS_TIMEOUT')
                    origin.stall = False
                    wrong = copy.deepcopy(node)
                    wrong['outbound']['obfs']['password'] = 'SECRET-wrong'
                    core.start(wrong, 'all')
                    with patch.dict(probe.STAGE_TIMEOUTS, {'SOCKS_CONNECT': .5}):
                        with self.assertRaises(ConnectionCheckError) as caught:
                            probe.check_connection(core.port)
                    self.assertEqual(caught.exception.code, 'SOCKS_CONNECT_TIMEOUT')
                    wrong = copy.deepcopy(node)
                    wrong['outbound']['password'] = 'SECRET-wrong'
                    core.start(wrong, 'all')
                    with self.assertRaises(ConnectionCheckError) as caught:
                        probe.check_connection(core.port)
                    self.assertIn(caught.exception.code, ('SOCKS_REPLY_1', 'SOCKS_REPLY_2'))
                    self.assertIn('[HYSTERIA_AUTHENTICATION]', core.connection_hint())
                    self.assertNotIn('SECRET', str(caught.exception) + core.connection_hint())
                    self.assertFalse(list((data / 'client').glob('core-*.json')))
            finally:
                core.stop()
                server.terminate()
                server.wait(timeout=5)
                server.stderr.close()
                Origin.stalled.set()
                origin.shutdown()
                origin.server_close()


if __name__ == '__main__':
    unittest.main()
