import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from relay_auditor.controller import Service
from relay_auditor.server import make_server
from relay_auditor.storage import Store, safe_snapshot
from test_service import FakeClient


class LocalBoundaryTests(unittest.TestCase):
    def test_unknown_output_fields_and_error_text_are_removed(self):
        result = safe_snapshot({'schema_version': 1, 'api_key': 'PRIVATE-KEY',
                                'status': 'PRIVATE-RAW', 'error_code': 'https://private.invalid/key',
                                'base_url': 'https://private.invalid', 'targets': [{'raw_response': 'PRIVATE'}]})
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('private.invalid', json.dumps(result))

    def test_invalid_control_does_not_partially_enable_detection(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        service = Service(store, client_factory=FakeClient)
        alias = service.configure('https://relay.example/v1', 'k', 'model-a')
        with self.assertRaises(ValueError):
            service.control(alias, enabled=True, interval_seconds=-1)
        self.assertFalse(service.snapshot()['targets'][0]['enabled'])

    def test_worker_reads_synthetic_logs_without_exposing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, output = root/'source', root/'output'
            (home/'sessions').mkdir(parents=True)
            output.mkdir()
            events = [
                {'type': 'session_meta', 'payload': {'id': 'PRIVATE-ID', 'model_provider': 'PRIVATE-PROVIDER'}},
                {'type': 'turn_context', 'payload': {'turn_id': 'PRIVATE-TURN', 'model': 'model-a'}},
                {'type': 'token_usage_record', 'payload': {'response_id': 'PRIVATE-RESPONSE', 'thread_id': 'PRIVATE-ID',
                    'turn_id': 'PRIVATE-TURN', 'usage': {'input_tokens': 10, 'output_tokens': 5}}},
            ]
            content = '\n'.join(json.dumps(row) for row in events)+'\n'
            (home/'sessions'/'synthetic.jsonl').write_text(content, encoding='utf-8')
            command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve().parents[1]/'usage_worker.py')]
            response = subprocess.run(command, input=json.dumps({'home': str(home), 'output': str(output), 'targets': []}).encode(),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(response.returncode, 0)
            self.assertEqual(response.stderr, b'')
            result = json.loads(response.stdout)
            self.assertEqual(result['usage']['observed_local_tokens'], 15)
            self.assertNotIn('PRIVATE', response.stdout.decode())
            self.assertEqual((home/'sessions'/'synthetic.jsonl').read_text(encoding='utf-8'), content)

    def test_loopback_origin_routes_and_no_config_echo(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = temporary.name
        if True:
            store = Store(directory)
            self.addCleanup(store.close)
            service = Service(store, client_factory=FakeClient)
            server = make_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            origin = f'http://127.0.0.1:{server.server_port}'
            prefix = server.session_path
            last_headers = {}
            def request(method, path, body=None, headers=None):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                connection.request(method, path, body, headers or {})
                result = connection.getresponse()
                last_headers.clear()
                last_headers.update(dict(result.getheaders()))
                payload = result.read()
                status = result.status
                connection.close()
                return status, payload
            self.assertEqual(request('GET', '/state')[0], 403)
            self.assertEqual(request('GET', prefix+'state', headers={'Origin': 'https://evil.invalid'})[0], 403)
            self.assertEqual(request('POST', prefix+'configure', '{}')[0], 403)
            body = json.dumps({'base_url': 'https://relay.example/v1', 'api_key': 'PRIVATE-KEY', 'model': 'model-a'})
            headers = {'Origin': origin, 'X-Relay-Request': '1', 'Content-Type': 'application/json'}
            self.assertEqual(request('POST', prefix+'configure', body, headers)[0], 200)
            status, payload = request('GET', prefix+'state')
            self.assertEqual(status, 200)
            self.assertNotIn(b'PRIVATE', payload)
            self.assertNotIn(b'relay.example', payload)
            service.configure('https://other.example/v1', 'PRIVATE-KEY', 'gpt-test', display_name='PRIVATE-NAME')
            status, payload = request('GET', prefix+'assessment')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(payload)['snapshot_type'], 'assessment')
            self.assertNotIn(b'display_names', payload)
            self.assertNotIn(b'PRIVATE', payload)
            self.assertEqual(request('GET', prefix+'assessment', headers={'Origin': 'https://evil.invalid'})[0], 403)
            self.assertEqual(json.loads(request('GET', prefix+'usage')[1])['snapshot_type'], 'usage')
            self.assertEqual(request('GET', prefix+'../agent.md')[0], 404)
            status, page = request('GET', prefix)
            self.assertEqual(status, 200)
            self.assertIn("connect-src 'self'", last_headers['Content-Security-Policy'])
            self.assertNotIn(b'https://', page)

    def test_catalog_selection_rejects_a_replaced_directory_batch(self):
        from relay_auditor.catalog import Catalog, ProviderSpec
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        service = Service(store, client_factory=FakeClient)
        service.catalog = Catalog([ProviderSpec('relay','model-a','responses',False,'https://relay.example/v1','synthetic-key')])
        old_id = service.catalog.catalog_id
        service.catalog = Catalog([ProviderSpec('relay','model-a','responses',False,'https://changed.example/v1','synthetic-key')])
        server = make_server(service)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        body=json.dumps({'source_alias':'catalog-1','catalog_id':old_id})
        connection.request('POST',server.session_path+'catalog_select',body,{'Origin':f'http://127.0.0.1:{server.server_port}',
                           'X-Relay-Request':'1','Content-Type':'application/json'})
        response=connection.getresponse(); response.read()
        self.assertEqual(response.status,400)
        self.assertEqual(service.snapshot()['targets'],[])
        connection.close()


if __name__ == '__main__':
    unittest.main()
