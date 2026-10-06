import base64
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from runtime import Core, ROOT, CREATE_NO_WINDOW, chrome_args
from subscription import SubscriptionError, make_config, parse_link, parse_subscription

UUID = '11111111-1111-4111-8111-111111111111'
VLESS = f'vless://{UUID}@127.0.0.1:443?security=none#Test'
HY2 = 'hysteria2://user%3Apass@127.0.0.1:443?sni=localhost#HY2'


class SubscriptionTests(unittest.TestCase):
    def test_base64_and_unicode(self):
        text = HY2 + '\n' + HY2.replace('#HY2', '#%D0%A2%D0%B5%D1%81%D1%82')
        nodes, skipped = parse_subscription(base64.b64encode(text.encode()).decode().rstrip('='))
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1]['name'], 'Тест')
        self.assertEqual(nodes[1]['outbound']['password'], 'user:pass')
        self.assertEqual(skipped, [])

    def test_alias_tls_and_domain_resolver(self):
        node = parse_link('hy2://secret@example.org:8443?peer=example.net&alpn=h3#Name')
        self.assertEqual(node['outbound']['tls'], {
            'enabled': True, 'server_name': 'example.net', 'alpn': ['h3']})
        self.assertEqual(make_config(node, 12345)['outbounds'][0]['domain_resolver'], 'bootstrap')
        self.assertEqual(node['outbound']['password'], 'secret')

    def test_ipv6_hysteria_obfs(self):
        node = parse_link('hy2://secret@[::1]:8443?obfs=salamander&obfs-password=abc')
        self.assertEqual(node['outbound']['server'], '::1')
        self.assertEqual(node['outbound']['obfs']['password'], 'abc')

    def test_hysteria_port_hopping(self):
        node = parse_link(HY2.replace('#HY2', '&mport=443,8443-8450,9000:9002'))
        self.assertEqual(node['outbound']['server_ports'], ['443:443', '8443:8450', '9000:9002'])
        self.assertNotIn('server_port', node['outbound'])
        for ports in ('0', '65536', '9000-8000', '443,', '-443', 'abc', '1:2:3'):
            with self.subTest(ports=ports), self.assertRaises(SubscriptionError):
                parse_link(HY2.replace('#HY2', '&mport=' + ports))

    def test_reject_other_protocols_and_insecure_tls(self):
        for link in (VLESS, 'hysteria://secret@localhost', 'ss://unsupported',
                     'https://example.com/', HY2.replace('#HY2', '&insecure=1'),
                     HY2.replace('#HY2', '&security=none'), HY2.replace('#HY2', '&pinSHA256=abc'),
                     HY2.replace('#HY2', '&obfs=salamander')):
            with self.subTest(link=link), self.assertRaises(SubscriptionError):
                parse_link(link)

    def test_mixed_subscription_keeps_only_hysteria2(self):
        for text in (VLESS + '\n' + HY2 + '\nss://unsupported',
                     base64.b64encode((VLESS + '\n' + HY2 + '\nss://unsupported').encode()).decode()):
            nodes, errors = parse_subscription(text)
            self.assertEqual([n['outbound']['type'] for n in nodes], ['hysteria2'])
            self.assertEqual(errors, [1, 3])
        with self.assertRaisesRegex(SubscriptionError, 'hysteria2://'):
            parse_subscription(VLESS)

    def test_config_rejects_non_hysteria_even_without_parser(self):
        with self.assertRaises(SubscriptionError):
            make_config({'outbound': {'type': 'vless', 'server': 'localhost'}}, 17890)

    def test_zero_port_is_rejected(self):
        with self.assertRaises(SubscriptionError):
            parse_link(HY2.replace(':443', ':0'))

    def test_html_json_rejected(self):
        for value in ('<html>login</html>', '{"outbounds": []}', ''):
            with self.subTest(value=value), self.assertRaises(SubscriptionError):
                parse_subscription(value)

    def test_no_direct_fallback(self):
        config = make_config(parse_link(HY2), 17890, 'all')
        self.assertEqual(config['route']['final'], 'vpn')
        self.assertEqual([o['type'] for o in config['outbounds']], ['hysteria2'])
        self.assertEqual(config['inbounds'][0]['listen'], '127.0.0.1')
        flags = chrome_args('chrome.exe', port=23456)
        self.assertIn('--proxy-bypass-list=<-loopback>', flags)
        self.assertIn('--force-webrtc-ip-handling-policy=disable_non_proxied_udp', flags)

    def test_split_routes_and_final_vpn(self):
        config = make_config(parse_link(HY2), 17890, 'ru-direct')
        self.assertEqual(config['route']['final'], 'vpn')
        self.assertEqual([o['type'] for o in config['outbounds']], ['hysteria2', 'direct'])
        self.assertEqual(len(config['dns']['servers']), 1)
        self.assertTrue(all(r['action'] == 'route' for r in config['route']['rules']))
        self.assertEqual(config['route']['rules'][0]['outbound'], 'direct')
        with self.assertRaises(ValueError):
            make_config(parse_link(HY2), 17890, 'unknown')


def unused_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(b'VPN integration passed')))
        self.end_headers()
        self.wfile.write(b'VPN integration passed')

    def log_message(self, *_):
        pass


@unittest.skipUnless((ROOT / 'bin/sing-box.exe').exists(), 'Run prepare.py first')
class CoreTests(unittest.TestCase):
    def test_automatic_ports_coexist_with_an_occupied_legacy_port_and_restart(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, socket.socket() as occupied:
            # If another user already owns it, leave their listener alone.
            try:
                occupied.bind(('127.0.0.1', 17892))
                occupied.listen()
            except OSError:
                pass
            first = Core(data=Path(directory) / 'first')
            second = Core(data=Path(directory) / 'second')
            try:
                first.start(parse_link(HY2), 'all')
                second.start(parse_link(HY2), 'all')
                self.assertNotEqual(first.port, second.port)
                self.assertNotIn(17892, (first.port, second.port))
                self.assertTrue(first.alive() and second.alive())
                first.stop()
                self.assertIsNone(first.port)
                self.assertTrue(second.alive())
                with socket.create_connection(('127.0.0.1', second.port), timeout=2) as probe:
                    probe.sendall(b'\x05\x01\x00')
                    self.assertEqual(probe.recv(2), b'\x05\x00')
                first.start(parse_link(HY2), 'all')
                self.assertNotEqual(first.port, second.port)
                self.assertEqual(first.port, first.diagnostics.listener_port())
                self.assertFalse(list(Path(directory).rglob('core-*.json')))
            finally:
                first.stop()
                second.stop()

    def test_config_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / 'check.json'
            binary = ROOT / 'bin/sing-box.exe'
            links = (HY2, HY2.replace('127.0.0.1', 'example.com'),
                     HY2.replace('#HY2', '&obfs=salamander&obfs-password=secret'),
                     HY2.replace('#HY2', '&mport=443,8443-8450'))
            for link in links:
                for mode in ('all', 'ru-direct'):
                    with self.subTest(link=link, mode=mode):
                        path.write_text(json.dumps(make_config(parse_link(link), 17890, mode)))
                        result = subprocess.run([str(binary), 'check', '-c', str(path)],
                                                capture_output=True, creationflags=CREATE_NO_WINDOW)
                        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_local_hysteria2_end_to_end_and_stop(self):
        self.exercise_protocol('hysteria2')

    def exercise_protocol(self, protocol):
        binary = ROOT / 'bin/sing-box.exe'
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            data = Path(directory)
            server_port, client_port = unused_port(), unused_port()
            origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
            threading.Thread(target=origin.serve_forever, daemon=True).start()
            server = None
            core = Core(data=data, port=client_port)
            try:
                inbound = {'type': protocol, 'listen': '127.0.0.1', 'listen_port': server_port}
                generated = subprocess.run([str(binary), 'generate', 'tls-keypair', 'localhost'],
                                           capture_output=True, check=True, creationflags=CREATE_NO_WINDOW).stdout.decode()
                cert_start = generated.index('-----BEGIN CERTIFICATE-----')
                cert_end = generated.index('-----END CERTIFICATE-----') + len('-----END CERTIFICATE-----')
                key_start = generated.index('-----BEGIN PRIVATE KEY-----')
                key_end = generated.index('-----END PRIVATE KEY-----') + len('-----END PRIVATE KEY-----')
                certificate, key = generated[cert_start:cert_end], generated[key_start:key_end]
                inbound['users'] = [{'password': 'user:pass'}]
                inbound['tls'] = {'enabled': True, 'certificate': [certificate], 'key': [key]}
                node = parse_link(HY2.replace(':443', f':{server_port}'))
                node['outbound']['tls']['certificate'] = [certificate]
                config = {'log': {'level': 'error'}, 'inbounds': [inbound], 'outbounds': [{'type': 'direct'}]}
                path = data / 'server.json'
                path.write_text(json.dumps(config))
                server = subprocess.Popen([str(binary), 'run', '-c', str(path)],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                          creationflags=CREATE_NO_WINDOW)
                core.start(node, 'all')
                self.assertEqual(core.binary, binary, 'Hysteria 2 must use the default sing-box core')
                self.assertFalse(list(data.glob('core-*.json')), 'Credentials must be removed after startup')
                with requests.Session() as client:
                    client.trust_env = False
                    url = f'http://127.0.0.1:{origin.server_port}/'
                    proxies = {'http': f'socks5h://127.0.0.1:{client_port}'}
                    for attempt in range(20):
                        try:
                            response = client.get(url, proxies=proxies, timeout=2)
                            self.assertEqual(response.content, b'VPN integration passed')
                            break
                        except requests.RequestException:
                            if server.poll() is not None:
                                self.fail(server.stderr.read().decode(errors='replace'))
                            if attempt == 19:
                                raise
                            time.sleep(.1)
                    child = core.process
                    # Exercise SOCKS5, which Chrome uses, including a domain-name target.
                    with socket.create_connection(('127.0.0.1', client_port), timeout=5) as sock:
                        sock.sendall(b'\x05\x01\x00')
                        self.assertEqual(sock.recv(2), b'\x05\x00')
                        domain = b'localhost'
                        sock.sendall(b'\x05\x01\x00\x03' + bytes([len(domain)]) + domain + origin.server_port.to_bytes(2, 'big'))
                        stream = sock.makefile('rb')
                        header = stream.read(4)
                        self.assertEqual(header[:2], b'\x05\x00')
                        length = {1: 4, 4: 16}.get(header[3])
                        if header[3] == 3:
                            length = stream.read(1)[0]
                        stream.read(length + 2)
                        sock.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
                        while True:
                            line = stream.readline()
                            self.assertTrue(line, 'Unexpected EOF in SOCKS response')
                            if line == b'\r\n':
                                break
                        self.assertEqual(stream.read(len(b'VPN integration passed')), b'VPN integration passed')
                        stream.close()
                    core.stop()
                    self.assertIsNotNone(child.poll())
                    with self.assertRaises(requests.RequestException):
                        client.get(url, proxies=proxies, timeout=1)
            finally:
                core.stop()
                if server is not None:
                    server.terminate()
                    server.wait(timeout=5)
                    server.stderr.close()
                origin.shutdown()
                origin.server_close()

    def test_busy_port_is_not_hijacked(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            core = Core(port=occupied.getsockname()[1])
            with self.assertRaisesRegex(RuntimeError, 'занят'):
                core.start(parse_link(HY2))
            self.assertFalse(core.alive())


if __name__ == '__main__':
    unittest.main()
