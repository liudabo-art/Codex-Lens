import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from relay_auditor.controller import Service
from relay_auditor.profiles import Profiles
from relay_auditor.server import make_server
from relay_auditor.storage import Store
from test_sdk_exports import FakeVault
from test_service import FakeClient


class TargetDeletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = Store(self.root / 'data')
        self.addCleanup(self.store.close)
        self.vault = FakeVault()
        self.profiles = Profiles(self.root / 'settings', vault=self.vault)
        self.service = Service(self.store, profiles=self.profiles, client_factory=FakeClient)
        self.addCleanup(self.service.stop)

    def add_target(self, name):
        alias = self.service.configure('https://relay.example/v1', 'fixture-key-' + name, 'gpt-test',
                                       display_name=name, save_credentials=True)
        return alias, self.service.monitors[alias].target_id

    def wait_idle(self):
        deadline = time.monotonic() + 3
        while self.service.busy and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.service.busy)

    def test_delete_preserves_history_and_other_keys_without_reusing_alias(self):
        a, a_id = self.add_target('A')
        b, b_id = self.add_target('B')
        c, c_id = self.add_target('C')
        self.service.run(b, 'quality', samples=2)
        self.service.control(b, enabled=True)
        before = self.store.budget()['requests']

        self.service.delete_target(b_id)
        self.assertNotIn(b, self.service.monitors)
        self.assertIsNone(self.vault.read(b_id))
        self.assertEqual(self.vault.read(a_id), {'relay': 'fixture-key-A'})
        self.assertEqual(self.vault.read(c_id), {'relay': 'fixture-key-C'})
        self.assertEqual(self.store.history()[0]['target_id'], b_id)
        self.assertEqual(self.store.budget()['requests'], before)
        self.assertEqual(self.service.configure('https://relay.example/v1', 'fixture-key-D', 'gpt-test'), 'relay-4')

        self.service = Service(self.store, profiles=self.profiles, client_factory=FakeClient)
        self.assertEqual(set(self.service.monitors), {a, c, 'relay-4'})
        self.assertEqual(self.service.monitors[c].target_id, c_id)
        self.service.delete_target(self.service.monitors['relay-4'].target_id)
        self.service = Service(self.store, profiles=self.profiles, client_factory=FakeClient)
        self.assertEqual(self.service.configure('https://relay.example/v1', 'fixture-key-E', 'gpt-test'), 'relay-5')

    def test_legacy_settings_keep_their_aliases_when_first_write_is_delete(self):
        a, a_id = self.add_target('A')
        b, b_id = self.add_target('B')
        body = json.loads(self.profiles.path.read_text(encoding='utf-8'))
        body.pop('next_target_number', None)
        for row in body['profiles']:
            row.pop('source_alias', None)
        self.profiles.path.write_text(json.dumps(body), encoding='utf-8')

        self.service = Service(self.store, profiles=self.profiles, client_factory=FakeClient)
        self.assertEqual(self.service.monitors[a].target_id, a_id)
        self.service.delete_target(a_id)
        self.service = Service(self.store, profiles=self.profiles, client_factory=FakeClient)
        self.assertEqual(self.service.monitors[b].target_id, b_id)
        self.assertEqual(self.service.configure('https://relay.example/v1', 'fixture-key-C', 'gpt-test'), 'relay-3')

    def test_active_target_requires_stop_queued_target_is_cancelled(self):
        entered = threading.Event()
        release = threading.Event()

        class Blocking(FakeClient):
            def complete(client, case):
                entered.set()
                release.wait(2)
                return super().complete(case)

        self.service.client_factory = Blocking
        first, first_id = self.add_target('First')
        pending, pending_id = self.add_target('Pending')
        self.service.submit(first, 'quality', samples=1)
        try:
            self.assertTrue(entered.wait(1))
            queued = self.service.submit(pending, 'quality', samples=1)
            with self.assertRaisesRegex(ValueError, '^target_running$'):
                self.service.delete_target(first_id)
            self.service.delete_target(pending_id)
            self.assertEqual(self.service.jobs[queued]['state'], 'cancelled')
            self.assertNotIn(queued, self.service.pending)
        finally:
            release.set()
            self.wait_idle()
        self.assertEqual(self.store.budget()['requests'], 1)
        self.assertIsNone(self.vault.read(pending_id))

    def test_vault_failure_preserves_card_and_allows_retry(self):
        alias, target_id = self.add_target('A')
        with patch.object(self.vault, 'delete', side_effect=ValueError('fixture-vault-error')):
            with self.assertRaisesRegex(ValueError, '^vault_unavailable$'):
                self.service.delete_target(target_id)
        self.assertIn(alias, self.service.monitors)
        self.assertEqual(self.profiles.load()[0]['target_id'], target_id)
        self.assertEqual(self.vault.read(target_id), {'relay': 'fixture-key-A'})
        self.service.delete_target(target_id)
        self.assertNotIn(alias, self.service.monitors)

    def test_settings_write_failure_restores_deleted_vault_item(self):
        alias, target_id = self.add_target('A')
        with patch.object(self.profiles, '_write_state', side_effect=OSError('fixture-write-error')):
            with self.assertRaisesRegex(ValueError, '^profiles_unavailable$'):
                self.service.delete_target(target_id)
        self.assertIn(alias, self.service.monitors)
        self.assertEqual(self.profiles.load()[0]['target_id'], target_id)
        self.assertEqual(self.vault.read(target_id), {'relay': 'fixture-key-A'})

    def test_credential_restore_failure_locks_target_and_allows_retry(self):
        alias, target_id = self.add_target('A')
        self.service.control(alias, enabled=True)
        with (patch.object(self.profiles, '_write_state', side_effect=OSError('fixture-write-error')),
              patch.object(self.vault, 'write', side_effect=ValueError('fixture-vault-error'))):
            with self.assertRaisesRegex(ValueError, '^target_delete_rollback_failed$'):
                self.service.delete_target(target_id)
        self.assertFalse(self.service.monitors[alias].credential_ready)
        self.assertFalse(self.service.monitors[alias].enabled)
        self.assertEqual(self.profiles.load()[0]['target_id'], target_id)
        self.service.delete_target(target_id)
        self.assertNotIn(alias, self.service.monitors)

    def test_deletion_cleans_reference_only_saved_item(self):
        alias = self.service.configure('https://relay.example/v1', 'fixture-relay', 'gpt-test')
        target_id = self.service.monitors[alias].target_id
        self.profiles.save(self.profiles.load()[0] | {'reference_preset': 'openai', 'reference_saved': True})
        self.vault.write(target_id, {'official_reference': 'fixture-reference', 'official_preset': 'openai'})
        self.vault.available = False
        with self.assertRaisesRegex(ValueError, '^vault_unavailable$'):
            self.service.delete_target(target_id)
        self.assertIn(alias, self.service.monitors)
        self.vault.available = True
        self.service.delete_target(target_id)
        self.assertIsNone(self.vault.read(target_id))

    def test_http_requires_owned_target_id(self):
        alias, target_id = self.add_target('A')
        server = make_server(self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'

        def post(body):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            try:
                conn.request('POST', server.session_path + 'target_delete', json.dumps(body), {
                    'Origin': origin, 'Content-Type': 'application/json', 'X-Relay-Request': '1',
                })
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        self.assertEqual(post({'target_id': alias}), (400, {'ok': False, 'error': 'unknown_target'}))
        self.assertIn(alias, self.service.monitors)
        self.assertEqual(post({'target_id': target_id}), (200, {'ok': True}))
        self.assertNotIn(alias, self.service.monitors)
