import importlib
import json
from pathlib import Path
import tempfile
import unittest


class SuiteTests(unittest.TestCase):
    def test_generated_tasks_are_repeatable_graded_locally_and_do_not_execute_outputs(self):
        suites=importlib.import_module('relay_auditor.suites')
        for kind in ('constraints','code','repair','structured','tool_args','context'):
            for seed in range(4):
                case=suites.quality_case(kind,seed)
                self.assertEqual(case,suites.quality_case(kind,seed))
                self.assertTrue(case.grade(json.dumps({'answer':case.expected}))['correct'])
                self.assertFalse(case.grade('__import__("os").system("private")')['valid'])
                self.assertFalse(case.grade(json.dumps({'answer':None}))['correct'])
        self.assertNotEqual(suites.quality_case('code',1).prompt,suites.quality_case('code',2).prompt)

    def test_context_length_and_suite_input_limits_are_explicit(self):
        suites=importlib.import_module('relay_auditor.suites')
        small=suites.quality_case('context',1,context_chars=4096)
        large=suites.quality_case('context',1,context_chars=16384)
        self.assertGreater(len(large.prompt),len(small.prompt)+10000)
        self.assertEqual(small.expected,large.expected)
        with self.assertRaises(ValueError): suites.quality_case('context',1,context_chars=10**8)


class EvidenceTests(unittest.TestCase):
    def test_v1_records_never_become_calibrated_and_unknown_is_not_zero_quality(self):
        reports=importlib.import_module('relay_auditor.reports')
        old={'schema_version':1,'model':'gpt-test','identity_state':'screening_consistent','status':'ok'}
        value=reports.upgrade(old)
        self.assertEqual(value['schema_version'],2)
        self.assertEqual(value['validation_state'],'experimental')
        self.assertEqual(value['evidence_level'],'legacy_unverified')
        self.assertIsNone(value['dimensions']['quality']['accuracy'])
        self.assertNotIn('PRIVATE',json.dumps(reports.upgrade(old|{'api_key':'PRIVATE'})))

    def test_different_protocol_or_suite_does_not_create_a_decline_trend(self):
        reports=importlib.import_module('relay_auditor.reports')
        common={'schema_version':2,'target_id':'a'*32,'model':'gpt-test','mode':'quality','suite_version':'quality-v1',
                'protocol_id':'synthetic-v1-'+'b'*16,'reference_model':'gpt-test','capability_completed':10,
                'capability_valid':10,'capability_correct':10,'status':'ok','evaluated_at':'2026-11-03T00:00:00+00:00'}
        changed=common|{'protocol_id':'synthetic-v1-'+'c'*16,'capability_correct':0,'evaluated_at':'2026-11-04T00:00:00+00:00'}
        self.assertEqual(reports.trend([common,changed])['status'],'not_comparable')
        same=changed|{'protocol_id':common['protocol_id']}
        self.assertEqual(reports.trend([common,same])['status'],'historical_decline_signal')
        failed=same|{'status':'cancelled','evaluated_at':'2026-11-05T00:00:00+00:00'}
        self.assertEqual(reports.trend([common,same,failed])['status'],'not_comparable')


class ProfileTests(unittest.TestCase):
    def test_saved_configuration_has_no_plaintext_keys_and_restores_disabled(self):
        profiles=importlib.import_module('relay_auditor.profiles')
        from relay_auditor.storage import Store
        from relay_auditor.controller import Service
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'reports')
            repository=profiles.Profiles(Path(folder)/'private',vault=profiles.UnavailableVault())
            service=Service(store,profiles=repository)
            alias=service.configure('https://relay.example/v1','PRIVATE-KEY','gpt-test',display_name='我的配置')
            service.control(alias,enabled=True,interval_seconds=37,active_only=False)
            restored=Service(store,profiles=repository)
            self.assertFalse(restored.monitors['relay-1'].enabled)
            self.assertEqual(restored.monitors['relay-1'].interval_seconds,37)
            self.assertFalse(restored.monitors['relay-1'].credential_ready)
            with self.assertRaises(ValueError): restored.run('relay-1','screen')
            self.assertEqual(restored.ui_snapshot()['display_names']['relay-1'],'我的配置')
            self.assertNotIn('PRIVATE-KEY',(Path(folder)/'private/settings.json').read_text(encoding='utf-8'))
            store.close()

    def test_vault_failure_does_not_fall_back_to_a_plaintext_secret(self):
        profiles=importlib.import_module('relay_auditor.profiles')
        with tempfile.TemporaryDirectory() as folder:
            repository=profiles.Profiles(folder,vault=profiles.UnavailableVault())
            with self.assertRaises(ValueError): repository.save_secret('a'*32,{'relay':'PRIVATE'})
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=='__main__': unittest.main()
