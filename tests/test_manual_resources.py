import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from relay_auditor.controller import Service
from relay_auditor.manual import MANUAL_IMAGES, MANUAL_ROUTES
from relay_auditor.server import make_server
from relay_auditor.storage import Store


class ManualResourcesTests(unittest.TestCase):
    def test_illustrations_and_generated_guide_match_the_offline_manifest(self):
        root = Path(__file__).resolve().parents[1]
        guide = json.loads((root/'relay_auditor/web/manual/content.json').read_text(encoding='utf-8'))
        self.assertEqual({chapter['image'] for chapter in guide['chapters']}, set(MANUAL_IMAGES))
        self.assertEqual(len({chapter['id'] for chapter in guide['chapters']}), len(guide['chapters']))
        for filename in MANUAL_IMAGES:
            image = (root/'relay_auditor/web/manual'/filename).read_bytes()
            self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertLess(len(image), 2 * 1024 * 1024)
        import importlib.util
        spec = importlib.util.spec_from_file_location('manual_docs', root/'build_tools/manual_docs.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual((root/'docs/USER_MANUAL.md').read_text(encoding='utf-8'), generator.render())

    def test_manual_uses_only_fixed_same_origin_resource_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            service = Service(store)
            server = make_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for route in MANUAL_ROUTES:
                    with urlopen(server.local_url + route, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn("img-src 'self'", response.headers['Content-Security-Policy'])
                        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                for route in ('manual/missing.png', 'manual/../content.json', '../manual/content.json'):
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(server.local_url + route, timeout=5)
                    self.assertIn(failure.exception.code, (403, 404))
            finally:
                server.shutdown()
                thread.join(3)
                server.server_close()
                service.stop()
                store.close()
