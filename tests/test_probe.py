import contextlib
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import connection_probe as probe
from diagnostics import ConnectionCheckError
from runtime import check_connection, ROOT, CREATE_NO_WINDOW


def receive(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError()
        data.extend(part)
    return bytes(data)


@contextlib.contextmanager
def endpoint(handler):
    stopped = threading.Event()
    errors = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(2)
        def serve():
            try:
                with listener.accept()[0] as sock:
                    sock.settimeout(2)
                    handler(sock, stopped)
            except (OSError, EOFError):
                pass
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield listener.getsockname()[1]
        finally:
            stopped.set()
            worker.join(3)
            if worker.is_alive():
                raise AssertionError('Owned fixture did not stop')
            if errors:
                raise errors[0]


class ConnectionProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary = ROOT / 'bin/sing-box.exe'
        if not binary.exists():
            raise unittest.SkipTest('Run prepare.py first')
        cls.directory = tempfile.TemporaryDirectory(dir=ROOT)
        data = Path(cls.directory.name)
        generated = subprocess.run([str(binary), 'generate', 'tls-keypair', 'api.ipify.org'],
                                   check=True, capture_output=True, creationflags=CREATE_NO_WINDOW).stdout.decode()
        cert = generated[generated.index('-----BEGIN CERTIFICATE-----'):generated.index('-----END CERTIFICATE-----') + len('-----END CERTIFICATE-----')]
        key = generated[generated.index('-----BEGIN PRIVATE KEY-----'):generated.index('-----END PRIVATE KEY-----') + len('-----END PRIVATE KEY-----')]
        cls.cert = data / 'certificate.pem'
        cls.cert.write_text(cert)
        key_path = data / 'key.pem'
        key_path.write_text(key)
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.load_cert_chain(cls.cert, key_path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.requested = []
        self.trust = patch('connection_probe.certifi.where', return_value=str(self.cert))
        self.trust.start()
        self.addCleanup(self.trust.stop)
        self.limits = patch.dict(probe.STAGE_TIMEOUTS, {stage: .5 for stage in probe.STAGE_TIMEOUTS})
        self.limits.start()
        self.addCleanup(self.limits.stop)

    def socks(self, sock, address=b'\x01\x7f\x00\x00\x01'):
        self.assertEqual(receive(sock, 3), b'\x05\x01\x00')
        sock.sendall(b'\x05\x00')
        self.assertEqual(receive(sock, 4), b'\x05\x01\x00\x03')
        domain = receive(sock, receive(sock, 1)[0]).decode('ascii')
        self.requested.append((domain, int.from_bytes(receive(sock, 2), 'big')))
        sock.sendall(b'\x05\x00\x00' + address + b'\x01\xbb')

    def https(self, body=b'203.0.113.9\n', status=200, address=b'\x01\x7f\x00\x00\x01'):
        def handler(sock, stopped):
            self.socks(sock, address)
            with self.context.wrap_socket(sock, server_side=True) as tls:
                request = bytearray()
                while not request.endswith(b'\r\n\r\n'):
                    request.extend(receive(tls, 1))
                self.assertIn(b'Host: api.ipify.org\r\n', request)
                tls.sendall(f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
        return handler

    def expect(self, handler, code, stage):
        with endpoint(handler) as port:
            with self.assertRaises(ConnectionCheckError) as caught:
                check_connection(port)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.stage, stage)
        self.assertIn('[' + code + ']', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))
        return str(caught.exception)

    def test_success_uses_only_loopback_remote_dns_and_validates_ip(self):
        real_connect = socket.create_connection
        with endpoint(self.https()) as port, patch.dict('os.environ', {'HTTPS_PROXY': 'http://SECRET.invalid:9'}):
            with patch('connection_probe.socket.create_connection', wraps=real_connect) as dial:
                self.assertEqual(check_connection(port), '203.0.113.9')
            dial.assert_called_once_with(('127.0.0.1', port), timeout=.5)
        self.assertEqual(self.requested, [('api.ipify.org', 443)])

    def test_ipv6_and_domain_socks_replies_are_consumed(self):
        for address in (b'\x04' + bytes(16), b'\x03\x09localhost'):
            with self.subTest(address=address), endpoint(self.https(b'2001:db8::1\n', address=address)) as port:
                self.assertEqual(check_connection(port), '2001:db8::1')

    def test_greeting_timeout_and_closed_connection_are_distinct(self):
        def timeout(sock, stopped):
            receive(sock, 3)
            stopped.wait(2)
        self.expect(timeout, 'SOCKS_GREETING_TIMEOUT', 'SOCKS_GREETING')
        self.expect(lambda sock, stopped: receive(sock, 3), 'SOCKS_GREETING_CLOSED', 'SOCKS_GREETING')

    def test_connect_timeout_has_no_claim_of_udp_blocking(self):
        def handler(sock, stopped):
            receive(sock, 3)
            sock.sendall(b'\x05\x00')
            receive(sock, 4)
            stopped.wait(2)
        message = self.expect(handler, 'SOCKS_CONNECT_TIMEOUT', 'SOCKS_CONNECT')
        self.assertNotIn('UDP заблокирован', message)

    def test_socks_rejection_is_distinct_from_invalid_reply(self):
        for reply, code in ((b'\x05\x05\x00\x01', 'SOCKS_REPLY_5'),
                            (b'\x04\x00\x00\x01', 'SOCKS_REPLY_INVALID')):
            def handler(sock, stopped, reply=reply):
                receive(sock, 3)
                sock.sendall(b'\x05\x00')
                receive(sock, 4)
                sock.sendall(reply)
            self.expect(handler, code, 'SOCKS_CONNECT')

    def test_tls_timeout_after_socks_success_is_distinct(self):
        def handler(sock, stopped):
            self.socks(sock)
            stopped.wait(2)
        self.expect(handler, 'HTTPS_TLS_TIMEOUT', 'HTTPS_TLS')

    def test_tls_certificate_validation_is_enabled(self):
        self.trust.stop()
        with patch.dict(probe.STAGE_TIMEOUTS, {'HTTPS_TLS': 3}):
            self.expect(self.https(), 'HTTPS_CERTIFICATE', 'HTTPS_TLS')

    def test_https_headers_and_body_timeouts_are_distinct(self):
        for send_headers, code, stage in ((False, 'HTTP_HEADERS_TIMEOUT', 'HTTP_HEADERS'),
                                         (True, 'HTTP_BODY_TIMEOUT', 'HTTP_BODY')):
            def handler(sock, stopped, send_headers=send_headers):
                self.socks(sock)
                with self.context.wrap_socket(sock, server_side=True) as tls:
                    receive(tls, 1)
                    if send_headers:
                        tls.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 30\r\n\r\n203.0.113.9')
                    stopped.wait(2)
            self.expect(handler, code, stage)

    def test_trickling_http_headers_cannot_extend_deadline(self):
        def handler(sock, stopped):
            self.socks(sock)
            with self.context.wrap_socket(sock, server_side=True) as tls:
                receive(tls, 1)
                while not stopped.wait(.04):
                    tls.sendall(b'H')
        start = time.monotonic()
        self.expect(handler, 'HTTP_HEADERS_TIMEOUT', 'HTTP_HEADERS')
        self.assertLess(time.monotonic() - start, 2)

    def test_http_status_and_invalid_body_do_not_leak_response(self):
        self.expect(self.https(b'SECRET', status=503), 'HTTP_STATUS', 'HTTP_HEADERS')
        self.expect(self.https(b'SECRET<html>login</html>'), 'HTTP_INVALID_IP', 'HTTP_BODY')
        self.expect(self.https(b'SECRET' * 300), 'HTTP_INVALID_IP', 'HTTP_BODY')

    def test_invalid_port_is_rejected_before_network_access(self):
        with patch('connection_probe.socket.create_connection') as dial:
            for port in (None, True, 0, 65536, '1234'):
                with self.subTest(port=port), self.assertRaises(ConnectionCheckError) as caught:
                    check_connection(port)
                self.assertEqual(caught.exception.code, 'LOCAL_PROXY_PORT')
            dial.assert_not_called()


if __name__ == '__main__':
    unittest.main()
