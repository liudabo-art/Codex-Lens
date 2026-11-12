"""Controlled official study paths exercised entirely with synthetic completions."""
import json
import tempfile
import unittest
from unittest.mock import patch

from relay_auditor import calibration
from relay_auditor.official import restore_reference
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from relay_auditor.transport import Completion, EndpointError


class ExamCalibrationTests(unittest.TestCase):
    def plan(self, *, family='gpt', samples=120, scope='primary'):
        protocol = Protocol(wire_api='deepseek' if family == 'deepseek' else 'responses', reasoning_effort='high')
        return calibration.freeze(f'{family}-primary', f'{family}-alternative', protocol,
                                  suite='exam-v2', family=family, samples=samples, seed=42, scope=scope)

    def collect(self, manifest, scenario, client):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        store.set_limits(1000, 10_000_000)
        protocol = Protocol(**manifest['protocol'])
        preset = manifest['official_preset']
        primary = restore_reference(preset, 'synthetic-only', manifest['primary_model'], protocol)
        alternative = restore_reference(preset, 'synthetic-only', manifest['alternative_model'], protocol)
        with patch('relay_auditor.controller.Service.wait_for_retry', return_value=None):
            result = calibration.collect_trial(manifest, scenario, 0, 'pilot', primary, alternative,
                                               store, client_factory=client, date='2026-11-12')
        return result, store

    def test_frozen_exam_budget_keeps_full_paper_and_separate_retry_ceiling(self):
        small, large = self.plan(), self.plan(samples=180, family='deepseek')
        self.assertEqual((small['planned_requests'], large['planned_requests']), (52800, 79200))
        self.assertEqual((small['max_requests'], large['max_requests']), (63360, 95040))
        self.assertEqual((small['planned_retry_requests'], large['planned_retry_requests']), (10560, 15840))
        self.assertEqual(small['protocol']['reasoning_effort'], 'high')
        self.assertEqual(large['official_preset'], 'deepseek')
        self.assertEqual(large['protocol']['wire_api'], 'deepseek')
        self.assertEqual(small['pilot_trials'], 10)
        self.assertTrue({'exam', 'grading', 'suites'} <= small['implementation_hashes'].keys())
        calibration.validate(small)
        for field, value in [('samples', 180), ('suite_version', 'exam-v1'), ('family', 'deepseek')]:
            with self.assertRaisesRegex(ValueError, 'invalid_or_modified_study'):
                calibration.validate(small | {field: value})

    def test_exam_rejects_other_counts_cross_family_and_wrong_wire(self):
        for samples in (40, 119, 200):
            with self.assertRaises(ValueError): self.plan(samples=samples)
        with self.assertRaises(ValueError):
            calibration.freeze('deepseek-primary', 'deepseek-alternative', Protocol(),
                               suite='exam-v2', family='deepseek')
        with self.assertRaises(ValueError):
            calibration.freeze('gpt-primary', 'deepseek-alternative', Protocol(), suite='exam-v2', family='gpt')

    def test_actual_exam_grades_substitution_with_full_protocol_and_template_pilots(self):
        calls = []
        class Client:
            def __init__(self, target): self.target = target
            def complete(self, case):
                calls.append((self.target.model, self.target.protocol, case.seed))
                answer = case.expected if self.target.model.endswith('primary') else None
                return Completion(json.dumps({'answer': answer}), {'total_tokens': 30})
        manifest = self.plan(family='deepseek')
        row, store = self.collect(manifest, 'substitution', Client)
        self.assertTrue(row['complete'])
        self.assertTrue(row['detected'])
        self.assertEqual((row['valid_pairs'], row['regressions'], row['requests']), (120, 120, 240))
        self.assertEqual(row['alternative_calls'], 120)
        self.assertTrue(all(protocol == Protocol(**manifest['protocol']) for _, protocol, _ in calls))
        report = calibration.evaluate(manifest, [row])
        pilots = report['scenarios']['substitution']['pilot_templates']
        self.assertEqual(sum(item['sample_count'] for item in pilots), 240)
        self.assertEqual(sum(item['correct'] for item in pilots if item['source_kind'] == 'reference'), 120)
        self.assertEqual(sum(item['correct'] for item in pilots if item['source_kind'] == 'relay'), 0)
        self.assertEqual(store.usage()['reference_requests'], 240)
        self.assertEqual(store.history(), [])
        self.assertFalse(report['candidate_pass'])

    def test_exam_retries_same_item_and_records_interrupted_trial_without_discarding_it(self):
        attempts = {}
        class Recovering:
            def __init__(self, target): self.target = target
            def complete(self, case):
                key = (self.target.model, case.seed)
                attempts[key] = attempts.get(key, 0) + 1
                if len(attempts) == 1 and attempts[key] == 1: raise EndpointError('network_error')
                return Completion(json.dumps({'answer': case.expected}))
        manifest = self.plan()
        row, store = self.collect(manifest, 'healthy', Recovering)
        self.assertTrue(row['complete'])
        self.assertEqual((row['requests'], row['retry_requests']), (241, 1))
        # Healthy sends the same official model for both sides: one item has
        # two primary calls plus exactly one recovery attempt.
        self.assertEqual(max(attempts.values()), 3)
        calibration.checked_records(manifest, [row])
        class Failed:
            def __init__(self, target): pass
            def complete(self, case): raise EndpointError('network_error')
        failed, _ = self.collect(manifest, 'healthy', Failed)
        self.assertFalse(failed['complete'])
        self.assertFalse(failed['detected'])
        self.assertEqual((failed['requests'], failed['retry_requests']), (3, 2))
        validation = {key: value for key, value in failed.items() if key not in ('pilot_items', 'pilot_tasks')}
        report = calibration.evaluate(manifest, [validation | {'phase': 'validation'}])
        self.assertEqual(report['scenarios']['healthy']['unknown'], 1)
        self.assertEqual(report['scenarios']['healthy']['interval'][1], 1)

    def test_default_assessment_path_and_source_mismatch_remain_fail_closed(self):
        plan = calibration.freeze('gpt-primary', 'gpt-alternative', Protocol(), seed=42)
        self.assertEqual(plan['samples'], 40)
        self.assertEqual(plan['planned_requests'], 17600)
        plan['implementation_hashes']['exam'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'invalid_or_modified_study'):
            calibration.evaluate(plan, [])

    def test_exam_simulation_uses_full_papers_without_loading_a_store_or_credentials(self):
        from relay_auditor.simulation import simulate
        report = simulate(suite='exam-v2', family='deepseek', trials=2, seed=42)
        self.assertEqual(report['suite_version'], 'exam-v2')
        self.assertEqual(report['family'], 'deepseek')
        self.assertEqual(report['real_api_requests'], 0)
        self.assertEqual({row['pairs'] for row in report['paired']}, {120, 180})
        stable = report['no_reference']['stable']['rounds']
        self.assertEqual([row['correct'] for row in stable], [120, 108, 120, 108])
        self.assertTrue(all(row['submitted'] and row['reference_requests'] == 0 for row in stable))
        failed = report['no_reference']['one_failed_round']['rounds'][-1]
        self.assertFalse(failed['submitted'])
        self.assertLess(failed['valid'], 120)
        selected = simulate(suite='exam-v2', family='gpt', samples=180, trials=1, seed=42)
        self.assertEqual({row['pairs'] for row in selected['paired']}, {180})
        with self.assertRaises(ValueError): simulate(suite='exam-v2', samples=40, trials=1)

    def test_explicit_assessment_family_uses_its_official_retry_path_and_keeps_default_count(self):
        attempts = 0
        class Client:
            def __init__(self, target): self.target = target
            def complete(self, case):
                nonlocal attempts
                attempts += 1
                if attempts == 1: raise EndpointError('network_error')
                return Completion(json.dumps({'answer': case.expected}))
        manifest = calibration.freeze('deepseek-primary', 'deepseek-alternative', Protocol(wire_api='deepseek'),
                                      suite='assessment-v4', family='deepseek', seed=42)
        row, _ = self.collect(manifest, 'healthy', Client)
        self.assertEqual(manifest['samples'], 40)
        self.assertEqual(manifest['retry_policy']['max_retry_requests_per_trial'], 160)
        self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs']), (81, 1, 40))
        self.assertTrue(row['complete'])
        self.assertFalse(row['detected'])
        self.assertEqual(sum(item['sample_count'] for item in calibration.evaluate(manifest, [row])[
            'scenarios']['healthy']['pilot_templates']), 80)

    def test_mixed_scenario_retry_keeps_the_same_model_for_the_same_question(self):
        calls = []
        class Client:
            def __init__(self, target): self.target = target
            def complete(self, case):
                calls.append((self.target.model, case.seed))
                if len(calls) == 1: raise EndpointError('network_error')
                return Completion(json.dumps({'answer': case.expected}))
        manifest = self.plan(scope='extended')
        row, _ = self.collect(manifest, 'mixed_50', Client)
        self.assertTrue(row['complete'])
        self.assertEqual(calls[0], calls[1])

    def test_official_failure_pilot_remains_reportable_and_arbitrary_pilot_text_is_rejected(self):
        class Client:
            def __init__(self, target): pass
            def complete(self, case): raise EndpointError('reference_model_unavailable')
        manifest = self.plan()
        row, _ = self.collect(manifest, 'healthy', Client)
        self.assertFalse(row['complete'])
        self.assertEqual(calibration.evaluate(manifest, [row])['scenarios']['healthy']['pilot_trials'], 1)
        forged = dict(row)
        forged['pilot_items'] = [dict(item) for item in row['pilot_items']]
        forged['pilot_items'][0]['template'] = 'arbitrary_private_token'
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.evaluate(manifest, [forged])


if __name__ == '__main__': unittest.main()
