"""Exercise split routing with real sing-box clients and an isolated HY2 server.

No public DNS or websites are contacted. The server only accepts the named
test destinations and maps them to a different HTTP origin than direct traffic.
"""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import requests

from runtime import Core, ROOT, CREATE_NO_WINDOW
from subscription import make_config, parse_link
from test_core import unused_port

VPN_DOMAINS = ['chatgpt.com', 'cdn.oaistatic.com', 'files.oaiusercontent.com',
               'openai.com', 'challenges.cloudflare.com', 'outside.example']
DIRECT_DOMAINS = ['example.ru', 'example.su', 'example.xn--p1ai',
                  'intranet', 'printer.local', 'router.home.arpa']


def origin_handler(marker):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(marker)))
            self.end_headers()
            self.wfile.write(marker)

        def log_message(self, *_):
            pass
    return Handler


@unittest.skipUnless((ROOT / 'bin/sing-box.exe').exists(), 'Run prepare.py first')
class SplitRoutingTests(unittest.TestCase):
    def setUp(self):
        self.resources = contextlib.ExitStack()
        self.addCleanup(self.resources.close)
        self.directory = Path(self.resources.enter_context(tempfile.TemporaryDirectory(dir=ROOT)))
        self.direct = self.start_origin(b'DIRECT')
        self.tunnel = self.start_origin(b'VPN')
        self.core = Core(data=self.directory, port=unused_port())
        self.resources.callback(self.core.stop)
        binary = ROOT / 'bin/sing-box.exe'
        generated = subprocess.run([str(binary), 'generate', 'tls-keypair', 'localhost'],
                                   capture_output=True, check=True, creationflags=CREATE_NO_WINDOW).stdout.decode()
        def pem(kind):
            start, end = f'-----BEGIN {kind}-----', f'-----END {kind}-----'
            return generated[generated.index(start):generated.index(end) + len(end)]
        certificate = pem('CERTIFICATE')
        server_port = unused_port()
        self.node = parse_link(f'hy2://test-password@127.0.0.1:{server_port}?sni=localhost')
        self.node['outbound']['tls']['certificate'] = [certificate]
        config = {
            'log': {'level': 'error'},
            'inbounds': [
                {'type': 'hysteria2', 'listen': '127.0.0.1', 'listen_port': server_port,
                 'users': [{'password': 'test-password'}],
                 'tls': {'enabled': True, 'certificate': [certificate], 'key': [pem('PRIVATE KEY')]}},
                {'type': 'mixed', 'listen': '127.0.0.1', 'listen_port': unused_port(), 'tag': 'ready'}],
            'outbounds': [{'type': 'direct', 'tag': 'server-direct'}],
            'route': {'rules': [
                {'domain': VPN_DOMAINS + DIRECT_DOMAINS, 'action': 'route',
                 'outbound': 'server-direct', 'override_address': '127.0.0.1',
                 'override_port': self.tunnel.server_port},
                # In particular, 1.1.1.1:443 is unavailable, as on a restricted exit.
                {'action': 'reject'}]}}
        path = self.directory / 'server.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        server = subprocess.Popen([str(binary), 'run', '-c', str(path)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  creationflags=CREATE_NO_WINDOW)
        def stop_server():
            server.terminate()
            server.wait(timeout=5)
            server.stderr.close()
        self.resources.callback(stop_server)
        for _ in range(100):
            if server.poll() is not None:
                self.fail(server.stderr.read().decode(errors='replace'))
            try:
                with socket.create_connection(('127.0.0.1', config['inbounds'][1]['listen_port']), timeout=.1):
                    break
            except OSError:
                threading.Event().wait(.05)
        else:
            self.fail('Test HY2 server did not start')

    def start_origin(self, marker):
        server = ThreadingHTTPServer(('127.0.0.1', 0), origin_handler(marker))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.resources.callback(server.server_close)
        self.resources.callback(server.shutdown)
        return server

    def start_client(self, mode):
        def config(node, port, routing_mode):
            result = make_config(node, port, routing_mode)
            # Local DNS deliberately maps even foreign names to the direct origin.
            # The VPN route must pass names unchanged and never use this mapping.
            result['dns']['servers'][0] = {
                'type': 'hosts', 'tag': 'bootstrap',
                'predefined': {name: ['127.0.0.1'] for name in VPN_DOMAINS + DIRECT_DOMAINS}}
            return result
        with patch('runtime.make_config', side_effect=config):
            self.core.start(self.node, mode)

    def fetch(self, host):
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(f'http://{host}:{self.direct.server_port}/',
                                  proxies={'http': f'socks5h://127.0.0.1:{self.core.port}'}, timeout=5)
            response.raise_for_status()
            return response.content

    def test_foreign_domains_use_vpn_without_cloudflare_dns(self):
        for mode in ('all', 'ru-direct'):
            self.start_client(mode)
            for domain in VPN_DOMAINS:
                with self.subTest(mode=mode, domain=domain):
                    self.assertEqual(self.fetch(domain), b'VPN')

    def test_russian_and_local_destinations_are_direct(self):
        self.start_client('ru-direct')
        for domain in DIRECT_DOMAINS + ['127.0.0.1']:
            with self.subTest(domain=domain):
                self.assertEqual(self.fetch(domain), b'DIRECT')

    def test_foreign_request_never_falls_back_to_direct_when_vpn_is_unavailable(self):
        self.node['outbound']['server_port'] = unused_port()
        self.start_client('ru-direct')
        self.assertEqual(self.fetch('intranet'), b'DIRECT')
        with self.assertRaises(requests.RequestException):
            self.fetch('chatgpt.com')
