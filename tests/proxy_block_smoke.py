"""Check that Chrome's blocking endpoint cannot fall back to a direct request."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
fixture = ROOT / 'build' / ('proxy-block-' + uuid.uuid4().hex)
fixture.mkdir(parents=True)
browser = Path(os.environ['ProgramFiles']) / 'Google/Chrome/Application/chrome.exe'
requests = []
marker = b'COTTONCLUB_LOCAL_ORIGIN_REACHED'

class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.send_header('Content-Length', str(len(marker)))
        self.end_headers()
        self.wfile.write(marker)

    def log_message(self, *_):
        pass

origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
threading.Thread(target=origin.serve_forever, daemon=True).start()
try:
    url = f'http://127.0.0.1:{origin.server_port}/probe'
    def open_page(name, flags):
        result = subprocess.run([str(browser), '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--no-default-browser-check', '--disable-background-networking',
                                 '--user-data-dir=' + str(fixture / name), '--dump-dom',
                                 '--timeout=8000', *flags, url], capture_output=True,
                                timeout=45, creationflags=0x08000000)
        assert result.returncode == 0, result.stderr[-500:]
        return result.stdout
    assert marker in open_page('direct', ['--no-proxy-server'])
    before = len(requests)
    assert before > 0
    blocked = open_page('blocked', ['--proxy-server=socks5://127.0.0.1:0', '--proxy-bypass-list=<-loopback>'])
    assert marker not in blocked
    assert len(requests) == before, 'Chrome must not fall back to direct, including loopback destinations'
    # Chrome may produce no DOM when navigation fails. Confirm the origin is
    # still reachable directly, rather than depending on an error-page format.
    assert marker in open_page('direct-after', ['--no-proxy-server'])
    assert len(requests) > before
    print('Real Chrome blocking endpoint refused the request without direct/loopback fallback; direct baseline passed.')
finally:
    origin.shutdown()
    origin.server_close()
