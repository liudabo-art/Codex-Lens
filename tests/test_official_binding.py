import json
from pathlib import Path
import tempfile
import unittest

from relay_auditor.controller import Service
from relay_auditor.profiles import Profiles
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from relay_auditor.transport import EndpointError
from test_sdk_exports import FakeVault
from test_service import FakeClient


class ModelClient(FakeClient):
    catalog = ['gpt-5.6-sol']
    lookups = []
    failure = None
    reference_failure = None

    def list_models(self):
        self.lookups.append((self.target.base_url, self.target.api_key))
        if self.failure:
            raise EndpointError(self.failure)
        return self.catalog

    def complete(self, case):
        if self.target.role == 'reference' and self.reference_failure:
            raise EndpointError(self.reference_failure)
        return super().complete(case)


class OfficialBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.store = Store(directory)
        self.addCleanup(self.store.close)
        self.vault = FakeVault()
        self.profiles = Profiles(directory / 'synthetic-profiles', vault=self.vault)
        ModelClient.lookups = []
        ModelClient.calls = []
        ModelClient.failure = None
        ModelClient.reference_failure = None
        ModelClient.catalog = ['gpt-5.6-sol']
        self.service = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'gpt5.6sol',
                                            Protocol(wire_api='responses'), save_credentials=True)
        self.monitor = self.service.monitors[self.alias]

    def attach(self, *, save=False):
        return self.service.set_official_reference(self.monitor.target_id, 'openai', 'synthetic-official', save_credentials=save)

    def test_gpt_alias_matches_looked_up_official_id_and_preserves_relay_id(self):
        result = self.attach()
        self.assertEqual(result['reference_model'], 'gpt-5.6-sol')
        self.assertEqual(ModelClient.lookups, [('https://api.openai.com/v1', 'synthetic-official')])
        self.assertEqual(ModelClient.calls, [])
        self.assertEqual(self.monitor.target.model, 'gpt5.6sol')
        self.assertEqual(self.service.estimate(self.alias, 'assessment')['required_requests'], 20)
        report = self.service.run(self.alias, 'assessment', seed=42)
        self.assertEqual(report['paired_result']['valid_pairs'], 10)
        self.assertEqual(report['reference_preset'], 'openai')
        self.assertEqual(self.store.usage()['reference_requests'], 10)
        self.assertNotIn('synthetic-official', json.dumps(self.service.ui_snapshot()))

    def test_saving_official_key_is_independent_of_relay_key(self):
        self.attach(save=True)
        self.service.credentials(self.alias, 'another-synthetic-relay', save_credentials=False)
        restored = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        monitor = next(iter(restored.monitors.values()))
        self.assertFalse(monitor.credential_ready)
        self.assertEqual(monitor.reference.api_key, 'synthetic-official')
        self.assertEqual(monitor.reference.base_url, 'https://api.openai.com/v1')
        self.assertEqual(monitor.reference_preset, 'openai')

    def test_wrong_provider_fails_before_metadata_request(self):
        with self.assertRaisesRegex(ValueError, 'reference_provider_mismatch'):
            self.service.set_official_reference(self.monitor.target_id, 'deepseek', 'synthetic-key')
        self.assertEqual(ModelClient.lookups, [])

    def test_official_authorization_failure_leaves_relay_only(self):
        ModelClient.failure = 'authentication_failed'
        with self.assertRaisesRegex(EndpointError, 'authentication_failed'):
            self.attach()
        self.assertIsNone(self.monitor.reference)
        self.assertEqual(self.service.estimate(self.alias, 'assessment')['required_requests'], 10)

    def test_changing_declared_model_invalidates_pair_without_rerouting_key(self):
        self.attach(save=True)
        self.service.update_target(self.alias, display_name='Synthetic', model='gpt-5.6-terra')
        self.assertEqual(self.service.estimate(self.alias, 'assessment')['reference_state'], 'reference_mismatch')
        self.assertEqual(self.monitor.reference.model, 'gpt-5.6-sol')
        self.assertEqual(self.monitor.reference.base_url, 'https://api.openai.com/v1')

    def test_static_reference_failure_preserves_relay_scores_and_disables_reference(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'glm-5.1',
                                       Protocol(wire_api='chat'))
        monitor = self.service.monitors[alias]
        attached = self.service.set_official_reference(monitor.target_id, 'glm-cn', 'synthetic-cn')
        self.assertEqual(attached['reference_state'], 'reference_pending')
        self.assertEqual(ModelClient.lookups, [])
        self.assertEqual(self.service.estimate(alias, 'assessment')['required_requests'], 20)
        ModelClient.reference_failure = 'authentication_failed'
        report = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual((report['status'], report['failure_source'], report['retry_requests']), ('unavailable', 'reference', 0))
        self.assertEqual(report['capability_correct'], 1)
        self.assertEqual(report['paired_result']['valid_pairs'], 0)
        self.assertEqual(report['reference_error'], 'authentication_failed')
        self.assertEqual(report['dimensions']['reliability']['sample_count'], 2)
        self.assertEqual(report['assessment_counts'][1]['attempted'], 1)
        self.assertEqual(self.store.usage()['reference_requests'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)
        self.assertEqual(self.service.estimate(alias, 'assessment')['required_requests'], 10)

    def test_legacy_reference_key_migrates_only_on_explicit_replacement(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'deepseek-flash',
                                       Protocol(wire_api='deepseek'), reference_key='synthetic-legacy',
                                       save_credentials=True)
        monitor = self.service.monitors[alias]
        self.service.update_target(alias, display_name='Synthetic', model='deepseek-flash', wire_api='chat')
        restored = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        monitor = restored.monitors[alias]
        self.assertEqual(monitor.reference.base_url, 'https://api.deepseek.com')
        self.assertEqual(monitor.reference.api_key, 'synthetic-legacy')
        self.assertEqual(restored.estimate(alias, 'assessment')['required_requests'], 10)
        for mode in ('baseline', 'identity_audit', 'capability_audit', 'quality_audit'):
            self.assertEqual(restored.estimate(alias, mode)['status'], 'reference_required')
            self.assertEqual(restored.run(alias, mode, samples=1)['error_code'], 'reference_required')
        self.assertEqual(self.store.usage()['reference_requests'], 0)
        with self.assertRaisesRegex(ValueError, 'reference_provider_mismatch'):
            restored.set_official_reference(monitor.target_id, 'glm-cn', 'synthetic-cn', save_credentials=True)
        self.assertEqual(self.vault.read(monitor.target_id)['reference'], 'synthetic-legacy')
        ModelClient.catalog = ['deepseek-flash']
        restored.set_official_reference(monitor.target_id, 'deepseek', 'synthetic-independent', save_credentials=True)
        self.assertNotIn('reference', self.vault.read(monitor.target_id))
        self.assertEqual(restored.estimate(alias, 'assessment')['required_requests'], 20)

    def test_region_switch_requires_key_and_mismatched_vault_pin_cannot_unlock(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'glm-5.1',
                                       Protocol(wire_api='chat'), save_credentials=True)
        monitor = self.service.monitors[alias]
        self.service.set_official_reference(monitor.target_id, 'glm-cn', 'synthetic-cn', save_credentials=True)
        with self.assertRaisesRegex(ValueError, 'invalid_credential'):
            self.service.set_official_reference(monitor.target_id, 'glm-intl', '', save_credentials=True)
        self.assertEqual(self.vault.read(monitor.target_id)['official_preset'], 'glm-cn')
        self.service.set_official_reference(monitor.target_id, 'glm-intl', 'synthetic-intl', save_credentials=True)
        self.assertEqual(monitor.reference.base_url, 'https://api.z.ai/api/paas/v4')
        self.assertEqual(monitor.target.api_key, 'synthetic-relay')
        saved = self.vault.read(monitor.target_id)
        self.assertEqual(saved['official_reference'], 'synthetic-intl')
        self.vault.write(monitor.target_id, saved | {'official_preset': 'glm-cn'})
        restored = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.assertTrue(restored.monitors[alias].credential_ready)
        self.assertIsNone(restored.monitors[alias].reference)
        self.assertEqual(restored.estimate(alias, 'assessment')['reference_state'], 'reference_key_required')

    def test_retired_deepseek_id_cannot_pair_even_from_legacy_configuration(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'deepseek-v4-flash',
                                       Protocol(wire_api='deepseek'), reference_key='synthetic-legacy')
        monitor = self.service.monitors[alias]
        with self.assertRaisesRegex(ValueError, 'reference_model_retired'):
            self.service.set_official_reference(monitor.target_id, 'deepseek', 'synthetic-official')
        self.assertEqual(self.service.estimate(alias, 'assessment')['required_requests'], 10)
        self.assertEqual(self.service.estimate(alias, 'quality_audit')['status'], 'reference_required')
        report = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual(report['reference_error'], 'reference_model_retired')
        self.assertEqual(self.store.usage()['reference_requests'], 0)

    def test_relay_key_update_preserves_legacy_credential_in_its_original_slot(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'gpt-5.6-sol',
                                       Protocol(), reference_key='synthetic-legacy', save_credentials=True)
        target_id = self.service.monitors[alias].target_id
        self.vault.write(target_id, {'relay': 'synthetic-relay', 'reference': 'synthetic-legacy'})
        self.profiles.save(next(row for row in self.profiles.load() if row['target_id'] == target_id) |
                           {'reference_saved': False})
        restored = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        restored.credentials(alias, 'synthetic-session-relay', save_credentials=False)
        reopened = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.assertFalse(reopened.monitors[alias].credential_ready)
        self.assertEqual(reopened.monitors[alias].reference.api_key, 'synthetic-legacy')
        self.assertEqual(reopened.monitors[alias].reference.base_url, 'https://api.openai.com/v1')

    def test_legacy_credential_without_any_original_wire_is_never_routed(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'gpt-5.6-sol',
                                       Protocol(), reference_key='synthetic-legacy', save_credentials=True)
        target_id = self.service.monitors[alias].target_id
        self.vault.write(target_id, {'relay': 'synthetic-relay', 'reference': 'synthetic-legacy'})
        self.profiles.save(next(row for row in self.profiles.load() if row['target_id'] == target_id) |
                           {'reference_wire_api': None})
        restored = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.assertTrue(restored.monitors[alias].credential_ready)
        self.assertIsNone(restored.monitors[alias].reference)
        restored.control(alias, interval_seconds=60)
        reopened = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.assertIsNone(reopened.monitors[alias].reference)

    def test_specialist_audit_stops_on_first_official_authentication_failure(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic-relay', 'glm-5.1', Protocol(wire_api='chat'))
        monitor = self.service.monitors[alias]
        self.service.set_official_reference(monitor.target_id, 'glm-cn', 'synthetic-cn')
        ModelClient.reference_failure = 'authentication_failed'
        report = self.service.run(alias, 'identity_audit', samples=2)
        self.assertEqual(report['reference_error'], 'authentication_failed')
        self.assertEqual(report['evidence_level'], 'basic_observation')
        self.assertEqual(self.store.usage()['reference_requests'], 1)
        self.assertEqual(self.service.estimate(alias, 'assessment')['required_requests'], 10)

    def test_new_official_reference_does_not_pair_against_an_official_origin(self):
        alias = self.service.configure('https://api.mistral.ai/v1', 'synthetic-official-direct', 'mistral-small-latest',
                                       Protocol(wire_api='chat'))
        with self.assertRaisesRegex(ValueError, 'official_direct'):
            self.service.set_official_reference(self.service.monitors[alias].target_id, 'mistral', 'synthetic-reference')
        self.assertEqual(ModelClient.lookups, [])

    def test_deleted_target_cannot_make_followup_calls_from_a_stale_instance(self):
        stale = Service(self.store, profiles=self.profiles, client_factory=ModelClient)
        self.service.delete_target(self.monitor.target_id)
        result = stale.run(self.alias, 'assessment', seed=42)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(ModelClient.calls, [])


if __name__ == '__main__':
    unittest.main()
