import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from web_server import Dashboard


class WebTest(unittest.TestCase):
    def test_pages_and_index_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            (root / 'file.py').write_text('needleweb\n')
            server = Dashboard(('127.0.0.1', 0), str(Path(tmp) / 'db.sqlite3'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                def post(route, values):
                    return urlopen(Request(base + route, data=urlencode(values).encode(), headers={'Origin': base}), timeout=3)
                self.assertIn(b'Atomi Code Graph Search', urlopen(base, timeout=3).read())
                post('/add', {'path': str(root)})
                for _ in range(100):
                    status = json.load(urlopen(base + '/api/status', timeout=3))
                    if status and status[0]['status'] == 'ready':
                        break
                    time.sleep(.02)
                self.assertEqual(status[0]['files'], 1)
                self.assertIn(b'needleweb', urlopen(base + '/?q=needleweb', timeout=3).read())
                self.assertIn(b'Source graph', urlopen(base + '/graph', timeout=3).read())
                self.assertEqual(json.load(urlopen(base + '/api/graph?type=calls', timeout=3))['type'], 'calls')
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base + '/api/status', headers={'Host': 'evil.example'}), timeout=3)
                self.assertEqual(failure.exception.code, 403)
                post('/remove', {'path': str(root)})
                self.assertEqual(json.load(urlopen(base + '/api/status', timeout=3)), [])
                self.assertTrue((root / 'file.py').exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
