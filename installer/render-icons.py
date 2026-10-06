"""Render the supplied SVG with Chrome; regenerate PNG and Windows ICO assets."""
import base64
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'CottonClub VPN for Chrome/icons'
SIZES = (16, 32, 48, 128)


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.result = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and dict(attrs).get('id') == 'result':
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.result += data


def main():
    candidates = [Path(os.environ.get(name, '')) / 'Google/Chrome/Application/chrome.exe'
                  for name in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
    chrome = next((path for path in candidates if path.is_file()), None)
    if chrome is None:
        raise RuntimeError('Google Chrome is required to render the logo.')
    svg = (ICONS / 'logo.svg').read_bytes()
    assert ET.fromstring(svg).tag == '{http://www.w3.org/2000/svg}svg'
    data_url = 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii')
    page = '''<!doctype html><meta charset="utf-8"><pre id="result"></pre><script>
const image = new Image();
image.onload = () => {
  const results = {};
  for (const size of SIZES) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const scale = size * .9 / Math.max(image.naturalWidth, image.naturalHeight);
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    canvas.getContext('2d').drawImage(image, (size-width)/2, (size-height)/2, width, height);
    results[size] = canvas.toDataURL('image/png').split(',')[1];
  }
  document.getElementById('result').textContent = JSON.stringify(results);
};
image.src = DATA_URL;
</script>'''.replace('SIZES', json.dumps(SIZES)).replace('DATA_URL', json.dumps(data_url))
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='render-icons-', dir=ROOT / 'build') as directory:
        fixture = Path(directory)
        (fixture / 'render.html').write_text(page, encoding='utf-8')
        result = subprocess.run([str(chrome), '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--no-default-browser-check', '--user-data-dir=' + str(fixture / 'profile'),
                                 '--virtual-time-budget=3000', '--dump-dom', (fixture / 'render.html').as_uri()],
                                capture_output=True, timeout=90, creationflags=0x08000000)
        if result.returncode:
            raise RuntimeError('Chrome could not render the logo.')
        parser = ResultParser()
        parser.feed(result.stdout.decode('utf-8'))
        images = json.loads(parser.result)
    pngs = []
    for size in SIZES:
        png = base64.b64decode(images[str(size)], validate=True)
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', png[16:24]) == (size, size)
        (ICONS / f'icon-{size}.png').write_bytes(png)
        pngs.append(png)
    offset = 6 + 16 * len(SIZES)
    ico = bytearray(struct.pack('<HHH', 0, 1, len(SIZES)))
    for size, png in zip(SIZES, pngs):
        ico.extend(struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    (ICONS / 'app.ico').write_bytes(ico + b''.join(pngs))
    print('Rendered transparent CottonClub PNG icons and app.ico:', ', '.join(map(str, SIZES)))


if __name__ == '__main__':
    main()
