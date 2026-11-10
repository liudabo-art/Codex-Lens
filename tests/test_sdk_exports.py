import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timezone,timedelta

from relay_auditor.core import Auditor
from relay_auditor.reference import ReferencePack
from relay_auditor.exporting import html_report
from relay_auditor.protocol import Protocol
from relay_auditor.calibration import binomial_interval,freeze,validate
from relay_auditor.reports import explain
from relay_auditor.storage import safe_snapshot
from test_service import FakeClient


class FakeVault:
    available=True
    def __init__(self): self.items={}
    def read(self,key): return self.items.get(key)
    def write(self,key,value): self.items[key]=value.copy()
    def delete(self,key): self.items.pop(key,None)


class ProductIntegrationTests(unittest.TestCase):
    def test_report_history_matches_the_same_snapshot_without_extending_the_public_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder, client_factory=FakeClient) as core:
                alias = core.configure('https://relay.example/v1', 'private-key', 'gpt-test', display_name='PRIVATE-NAME')
                preview = core.estimate(alias, 'assessment')
                self.assertEqual((preview['target_requests'], preview['reference_requests']), (10, 0))
                core.run(alias, 'assessment', seed=42)
                ui = core.service.ui_snapshot()
                self.assertEqual(ui['history_reports'], [explain(row) for row in ui['history']])
                self.assertEqual(ui['report_cards'][alias], ui['history_reports'][0])
                self.assertEqual(core.store.usage()['probe_requests'], preview['target_requests'])
                self.assertNotIn('history_reports', core.snapshot())
                self.assertNotIn('PRIVATE-NAME', json.dumps(ui['history_reports']))

    def test_new_anonymous_evidence_is_allowlisted_without_raw_answers(self):
        report = safe_snapshot({'suite_version': 'assessment-v3', 'paired_result': {
            'planned_pairs': 10, 'loss_bounds': [-.1, .2]}, 'assessment_tasks': [
            {'task_kind': 'code_branch', 'correct': 2, 'prompt': 'private-prompt'}],
            'response_issues': [{'source_kind': 'relay', 'error_code': 'recovered_format', 'sample_count': 1}],
            'raw_response': 'private-output'})
        self.assertEqual(report['suite_version'], 'assessment-v3')
        self.assertEqual(report['paired_result']['loss_bounds'], [-.1, .2])
        self.assertEqual(report['assessment_tasks'], [{'task_kind': 'code_branch', 'correct': 2}])
        self.assertEqual(report['response_issues'][0]['error_code'], 'recovered_format')
        self.assertNotIn('private-', json.dumps(report))

    def test_host_can_preview_and_read_usage_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder, client_factory=FakeClient) as core:
                alias = core.configure('https://relay.example/v1', 'synthetic-key', 'gpt-test')
                self.assertEqual(core.estimate(alias, 'assessment')['required_requests'], 10)
                usage = core.usage_snapshot()
                self.assertEqual(usage['schema_version'], 2)
                self.assertEqual(usage['snapshot_type'], 'usage')
                self.assertEqual(usage['usage']['probe_requests'], 0)
                self.assertEqual(usage['usage']['source_kind'], 'unknown')
                self.assertNotIn('targets', usage)
                self.assertNotIn('synthetic-key', json.dumps(usage))

    def test_offline_demo_uses_injected_client_and_marks_synthetic_results(self):
        from relay_auditor.demo import snapshot
        with tempfile.TemporaryDirectory() as folder, patch('relay_auditor.transport.APIClient.complete',side_effect=AssertionError('network forbidden')):
            data=snapshot(folder)
            self.assertTrue(data['demonstration'])
            self.assertEqual(len(data['assessment']['comparisons']),2)
            self.assertIn('not model measurements',data['warning'])

    def test_saved_locked_estimate_needs_no_hidden_prompt_or_model_call(self):
        from relay_auditor.cli import main
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder,persist_settings=True,vault=FakeVault()) as core:
                core.configure('https://relay.example/v1','synthetic','gpt-test')
            output=io.StringIO()
            with patch('relay_auditor.cli.data_directory',return_value=folder),patch('relay_auditor.cli.hidden',side_effect=AssertionError('unexpected prompt')),redirect_stdout(output):
                self.assertEqual(main(['estimate','--target','relay-1','--mode','quality','--samples','5']),0)
            self.assertEqual(json.loads(output.getvalue())['required_requests'],5)

    def test_report_conversion_never_upgrades_legacy_on_second_conversion(self):
        from relay_auditor.reports import upgrade
        record={'schema_version':1,'model':'gpt-test','status':'ok'}
        self.assertEqual(upgrade(upgrade(record))['evidence_level'],'legacy_unverified')

    def test_opt_in_vault_restart_and_opt_out_preserve_order_and_private_separation(self):
        vault=FakeVault()
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder,persist_settings=True,vault=vault,client_factory=FakeClient) as core:
                a=core.configure('https://relay.example/v1','private-a','gpt-test',display_name='PRIVATE-A',save_credentials=True)
                b=core.configure('https://other.example/v1','private-b','gpt-test',display_name='PRIVATE-B')
                core.service.update_target(a,display_name='PRIVATE-A2',model='gpt-test')
                core.service.control(a,enabled=True,active_only=False)
                core.service.credentials(a,'private-new',save_credentials=True)
                self.assertFalse(core.service.monitors[a].enabled)
                self.assertNotIn('private-new',(Path(folder)/'private/settings.json').read_text(encoding='utf-8'))
            with Auditor(folder,persist_settings=True,vault=vault,client_factory=FakeClient) as restored:
                self.assertEqual(restored.service.monitors[a].display_name,'PRIVATE-A2')
                self.assertEqual(restored.service.monitors[b].display_name,'PRIVATE-B')
                self.assertTrue(restored.service.monitors[a].credential_ready)
                self.assertFalse(restored.service.monitors[b].credential_ready)
                self.assertFalse(restored.service.monitors[a].enabled)
                restored.service.credentials(a,'private-unsaved',save_credentials=False)
                self.assertEqual(vault.items,{})
                self.assertNotIn('PRIVATE',json.dumps(restored.snapshot()))

    def test_corrupt_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private/settings.json'; path.parent.mkdir(); path.write_text('broken',encoding='utf-8')
            with Auditor(folder,persist_settings=True,vault=FakeVault()) as core:
                self.assertEqual(core.service.settings_status,'unavailable')
                with self.assertRaises(ValueError): core.configure('https://relay.example/v1','key','gpt-test')
            self.assertEqual(path.read_text(),'broken')

    def test_paired_default_reserves_and_runs_forty_pairs_and_exports_no_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder,client_factory=FakeClient) as core:
                core.store.set_limits(1000,1000000)
                alias=core.configure('https://relay.example/v1','secret','gpt-test',display_name='PRIVATE-NAME',reference_key='official-secret')
                result=core.run(alias,'quality_audit')
                self.assertEqual(result['capability_completed'],40)
                self.assertEqual(core.store.budget()['requests'],80)
                self.assertEqual(result['evidence_level'],'matched_official_comparison')
                html=html_report(core.service.ui_snapshot()|{'api_key':'PRIVATE-KEY','display_names':{'relay-1':'<script>PRIVATE</script>'}})
                self.assertNotIn('PRIVATE',html); self.assertNotIn('https://',html); self.assertNotIn('<script',html)
                self.assertIn('experimental',html)

    def test_untrusted_reference_requires_exact_conditions_and_retains_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            with Auditor(folder,client_factory=FakeClient) as core:
                alias=core.configure('https://relay.example/v1','key','gpt-test')
                m=core.service.monitors[alias]
                pack=ReferencePack('gpt-test','gpt-test',Protocol().identity,datetime.now(timezone.utc).isoformat(),tuple(tuple([0.0]*429) for _ in range(12)))
                self.assertTrue(pack.matches(m.target,'gpt-test'))
                pack.install(core.store,m.target,'gpt-test')
                self.assertEqual(core.store.baseline('gpt-test',Protocol().identity,'gpt-test')['provenance_level'],'user_history')
                stale=ReferencePack('gpt-test','gpt-test',Protocol().identity,(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),pack.features)
                with self.assertRaises(ValueError): stale.install(core.store,m.target,'gpt-test')
                self.assertFalse(pack.matches(m.target,'other-model'))

    def test_exact_calibration_interval_and_source_integrity(self):
        self.assertAlmostEqual(binomial_interval(0,100)[1],.036216692645,places=9)
        self.assertGreater(binomial_interval(90,100)[0],.80)
        self.assertLess(binomial_interval(80,100)[0],.80)
        plan=freeze('gpt-primary','gpt-alternative',Protocol())
        validate(plan)
        self.assertIn('suites',plan['implementation_hashes'])
        with self.assertRaises(ValueError): validate(plan|{'implementation_hashes':{}})


if __name__=='__main__': unittest.main()
