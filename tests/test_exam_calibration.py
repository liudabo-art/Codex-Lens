"""Controlled official study paths exercised entirely with synthetic completions."""
import json
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from relay_auditor import calibration, exam
from relay_auditor.official import restore_reference
from relay_auditor.protocol import Protocol
from relay_auditor.storage import BudgetExceeded, Store
from relay_auditor.transport import Completion, EndpointError

GPT_PRIMARY = 'gpt-5.6-sol'
GPT_ALTERNATIVE = 'gpt-5.6-terra'
DEEPSEEK_PRIMARY = 'deepseek-flash'
DEEPSEEK_ALTERNATIVE = 'deepseek-v4-pro'


class CorrectClient:
    def __init__(self, target): self.target = target
    def complete(self, case):
        return Completion(json.dumps({'answer': case.expected}))


def wrong_answer(value):
    if isinstance(value, dict):
        result = dict(value)
        key = next(iter(result))
        result[key] = wrong_answer(result[key])
        return result
    if isinstance(value, list): return [wrong_answer(value[0]), *value[1:]] if value else [None]
    if type(value) is bool: return not value
    if type(value) is int: return value + 1
    if isinstance(value, str): return value + 'synthetic-wrong'
    raise AssertionError('unexpected_synthetic_answer_type')


class ExamCalibrationTests(unittest.TestCase):
    def plan(self, *, family='gpt', samples=120, scope='primary'):
        protocol = Protocol(wire_api='deepseek' if family == 'deepseek' else 'responses', reasoning_effort='high')
        primary, alternative = ((GPT_PRIMARY, GPT_ALTERNATIVE) if family == 'gpt'
                                else (DEEPSEEK_PRIMARY, DEEPSEEK_ALTERNATIVE))
        return calibration.freeze(primary, alternative, protocol,
                                  suite='exam-v2', family=family, samples=samples, seed=42, scope=scope)

    def collect(self, manifest, scenario, client, *, index=0):
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
            result = calibration.collect_trial(manifest, scenario, index, 'pilot', primary, alternative,
                                               store, client_factory=client, date='2026-11-12')
        return result, store

    def test_exam_pilot_reconstructs_seed_and_identity_for_both_families_and_sizes(self):
        for family in ('gpt', 'deepseek'):
            for samples in (120, 180):
                manifest = self.plan(family=family, samples=samples)
                for index in (0, 1):
                    for scenario, offset in (('healthy', 0), ('substitution', 10_000_000)):
                        with self.subTest(family=family, samples=samples, index=index, scenario=scenario):
                            row, _ = self.collect(manifest, scenario, CorrectClient, index=index)
                            self.assertEqual({item['seed'] for item in row['pilot_items']},
                                             set(range(42 + offset + index * 1000,
                                                       42 + offset + index * 1000 + samples)))
                            row['pilot_items'].reverse()
                            calibration.checked_records(manifest, [row])

    def test_trial_seed_preserves_frozen_phase_scenario_and_index_offsets(self):
        manifest = self.plan(scope='extended')
        for scenario, offset in (('healthy', 0), ('substitution', 10_000_000), ('mixed_50', 60_000_000)):
            self.assertEqual(calibration._trial_seed(manifest, scenario, 1, 'pilot'), 1042 + offset)
            self.assertEqual(calibration._trial_seed(manifest, scenario, 1, 'validation'), 1_000_001_042 + offset)

    def test_exam_pilot_rejects_wrong_legal_metadata_and_partial_slots(self):
        manifest = self.plan()
        row, _ = self.collect(manifest, 'healthy', CorrectClient)
        first = row['pilot_items'][0]
        changes = [
            {'template': next(item['template'] for item in row['pilot_items'] if item['template'] != first['template'])},
            {'seed': first['seed'] + 1}, {'difficulty': 4},
            {'task_kind': next(task for task in exam.EXAM_TASKS if task != first['task_kind'])},
        ]
        malformed = []
        for change in changes:
            items = copy.deepcopy(row['pilot_items'])
            items[0].update(change)
            malformed.append(items)
        swapped = copy.deepcopy(row['pilot_items'])
        for item in swapped:
            if item['question_number'] in (1, 2): item['question_number'] = 3 - item['question_number']
        malformed.extend([swapped, row['pilot_items'][:-1], row['pilot_items'][:1],
                          row['pilot_items'] + [first], [first] * 240, None, {}, []])
        for items in malformed:
            with self.subTest(shape=type(items).__name__, count=len(items) if items is not None else None):
                with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                    calibration.checked_records(manifest, [row | {'pilot_items': items}])

    def test_exam_pilot_reconciles_item_states_requests_retries_and_pairs(self):
        manifest = self.plan()
        row, _ = self.collect(manifest, 'healthy', CorrectClient)
        contradictions = [
            {'attempts': 0}, {'grading_issue': 'invalid_json'}, {'format_state': 'answer_format'},
            {'error_code': 'network_error'}, {'format_state': 'recovered_format'},
            {'correct': None, 'error_code': 'answer_format', 'format_state': 'answer_format'},
            {'correct': None}, {'format_state': None},
        ]
        for change in contradictions:
            items = copy.deepcopy(row['pilot_items'])
            items[0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | {'pilot_items': items}])
        for field, value in (('error_code', []), ('grading_issue', {})):
            items = copy.deepcopy(row['pilot_items'])
            items[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | {'pilot_items': items}])
        for change in ({'requests': 241}, {'retry_requests': 1}, {'attempted_pairs': 119},
                       {'valid_pairs': 119, 'complete': False, 'applied_audit_index': None},
                       {'regressions': 1, 'improvements': 1, 'p_value': .75}, {'p_value': .5}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | change])
        excess = copy.deepcopy(row)
        for item in [item for item in excess['pilot_items'] if item['source_kind'] == 'relay'][:25]:
            item['attempts'] = 2
        excess.update(requests=265, retry_requests=25)
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.checked_records(manifest, [excess])

    def test_exam_pilot_preserves_prestart_failure_partial_retry_and_cancel(self):
        manifest = self.plan()
        with patch('relay_auditor.planning.exam_plan', side_effect=BudgetExceeded()):
            prestart, _ = self.collect(manifest, 'healthy', CorrectClient)
        self.assertEqual((prestart['requests'], prestart['pilot_items']), (0, []))
        calibration.checked_records(manifest, [prestart])
        with patch.object(Store, 'reserve_batch', side_effect=BudgetExceeded()):
            initialized, _ = self.collect(manifest, 'healthy', CorrectClient)
        self.assertEqual(len(initialized['pilot_items']), 240)
        self.assertEqual(initialized['requests'], 0)
        calibration.checked_records(manifest, [initialized])
        pre_request_error = copy.deepcopy(initialized)
        pre_request_error['pilot_items'][0]['error_code'] = 'reference_required'
        calibration.checked_records(manifest, [pre_request_error])
        for failure, expected_requests, expected_retries in (
                ('authentication_failed', 5, 0), ('network_error', 7, 2), ('interrupt', 5, 0)):
            calls = 0
            class Client(CorrectClient):
                def complete(self, case):
                    nonlocal calls
                    calls += 1
                    if calls >= 5:
                        if failure == 'interrupt': raise KeyboardInterrupt()
                        raise EndpointError(failure)
                    return super().complete(case)
            row, _ = self.collect(manifest, 'healthy', Client)
            self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs'], row['attempted_pairs']),
                             (expected_requests, expected_retries, 2, 3))
            self.assertEqual(len(row['pilot_items']), 240)
            self.assertEqual(sum(item['correct'] is True for item in row['pilot_items']), 4)
            self.assertEqual(row['cancelled'], failure == 'interrupt')
            calibration.checked_records(manifest, [row])
            with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | {'attempted_pairs': 4}])
        original = calibration.Service.set_exam_progress
        def cancel_after_last(service, sides):
            original(service, sides)
            if sum(side['completed'] for side in sides) == 240: service.stop_event.set()
        with patch.object(calibration.Service, 'set_exam_progress', cancel_after_last):
            cancelled, _ = self.collect(manifest, 'healthy', CorrectClient)
        self.assertEqual((cancelled['requests'], cancelled['valid_pairs']), (240, 120))
        self.assertTrue(cancelled['cancelled'])
        self.assertFalse(cancelled['complete'])
        self.assertFalse(cancelled['detected'])
        self.assertIsNone(cancelled['applied_audit_index'])
        calibration.checked_records(manifest, [cancelled])

    def test_exam_pilot_diagnostics_match_exact_paired_counts(self):
        manifest = self.plan()
        class Categories(CorrectClient):
            def complete(self, case):
                category = (case.seed - 10_000_042) % 4
                reference = self.target.model == manifest['primary_model']
                correct = category == 0 or (category == 2 if reference else category == 3)
                return Completion(json.dumps({'answer': case.expected if correct else wrong_answer(case.expected)}))
        full, _ = self.collect(manifest, 'substitution', Categories)
        calls = 0
        class Partial(CorrectClient):
            def complete(self, case):
                nonlocal calls
                calls += 1
                if calls == 4: raise KeyboardInterrupt()
                return super().complete(case)
        partial, _ = self.collect(manifest, 'substitution', Partial, index=1)
        healthy, _ = self.collect(manifest, 'healthy', CorrectClient)
        report = calibration.evaluate(manifest, [partial, healthy, full])
        self.assertEqual(report['schema_version'], 2)
        diagnostic = report['scenarios']['substitution']['pilot_diagnostics']
        self.assertEqual({key: value for key, value in diagnostic.items() if key != 'templates'}, {
            'schema_version': 1, 'evidence': 'descriptive_pilot', 'evidence_state': 'available',
            'pilot_trials': 2, 'item_evidence_trials': 2, 'missing_item_evidence_trials': 0,
            'completed_trials': 1, 'cancelled_trials': 1,
        })
        templates = diagnostic['templates']
        keys = [(item['task_kind'], item['template'], item['difficulty']) for item in templates]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), 60)
        self.assertEqual([sum(item[field] for item in templates) for field in (
            'planned_pairs', 'attempted_pairs', 'valid_pairs', 'unknown_pairs',
            'both_correct', 'both_incorrect', 'regressions', 'improvements')],
            [240, 122, 121, 119, 31, 30, 30, 30])
        template = next(item for item in templates if (
            item['task_kind'], item['template'], item['difficulty']) == ('exam_reasoning', 'shortest_path', 2))
        side = {'attempted': 2, 'requests': 2, 'retry_requests': 0, 'scored': 2, 'correct': 1,
                'format_losses': 0, 'format_recovered': 0, 'unknown': 2, 'score_rate': .5}
        self.assertEqual(template, {
            'task_kind': 'exam_reasoning', 'template': 'shortest_path', 'difficulty': 2,
            'planned_pairs': 4, 'attempted_pairs': 2, 'valid_pairs': 2, 'unknown_pairs': 2,
            'both_correct': 0, 'both_incorrect': 0, 'regressions': 1, 'improvements': 1,
            'observed_score_gap': 0.0, 'reference': side, 'relay': side,
        })
        self.assertEqual([sum(item['reference'][field] for item in templates)
                          for field in ('attempted', 'requests', 'scored', 'correct', 'unknown')],
                         [122, 122, 122, 62, 118])
        self.assertEqual([sum(item['relay'][field] for item in templates)
                          for field in ('attempted', 'requests', 'scored', 'correct', 'unknown')],
                         [122, 122, 121, 61, 119])
        self.assertEqual(report['scenarios']['healthy']['pilot_diagnostics']['pilot_trials'], 1)
        self.assertEqual(sum(item['planned_pairs'] for item in report['scenarios']['healthy'][
            'pilot_diagnostics']['templates']), 120)
        reordered = [full | {'pilot_items': list(reversed(full['pilot_items']))}, healthy, partial]
        self.assertEqual(calibration.evaluate(manifest, reordered)['scenarios']['substitution'][
            'pilot_diagnostics'], diagnostic)

    def test_exam_pilot_diagnostics_distinguish_format_loss_unknown_and_retries(self):
        manifest = self.plan()
        calls = 0
        class Formats(CorrectClient):
            def complete(self, case):
                nonlocal calls
                calls += 1
                if calls == 1: raise EndpointError('network_error')
                if calls == 2: return Completion('Synthetic answer: ' + json.dumps({'answer': case.expected}))
                if calls == 3: return Completion('no JSON answer')
                if calls == 5: raise KeyboardInterrupt()
                return super().complete(case)
        partial, _ = self.collect(manifest, 'substitution', Formats)
        diagnostic = calibration.evaluate(manifest, [partial])['scenarios']['substitution']['pilot_diagnostics']
        self.assertEqual((diagnostic['completed_trials'], diagnostic['cancelled_trials']), (0, 1))
        templates = diagnostic['templates']
        self.assertEqual([sum(item[field] for item in templates) for field in (
            'planned_pairs', 'attempted_pairs', 'valid_pairs', 'unknown_pairs', 'regressions', 'improvements')],
            [120, 2, 1, 119, 0, 1])
        self.assertEqual([sum(item['reference'][field] for item in templates) for field in (
            'attempted', 'requests', 'retry_requests', 'scored', 'correct', 'format_losses', 'format_recovered', 'unknown')],
            [2, 2, 0, 2, 1, 1, 0, 118])
        self.assertEqual([sum(item['relay'][field] for item in templates) for field in (
            'attempted', 'requests', 'retry_requests', 'scored', 'correct', 'format_losses', 'format_recovered', 'unknown')],
            [2, 3, 1, 1, 1, 0, 1, 119])
        observed = next(item for item in templates if item['valid_pairs'])
        self.assertEqual(observed['observed_score_gap'], -1.0)
        self.assertEqual(observed['reference']['score_rate'], 0.0)
        self.assertEqual(observed['relay']['score_rate'], 1.0)
        for item in templates:
            if item['attempted_pairs'] == 0:
                self.assertIsNone(item['observed_score_gap'])
                self.assertIsNone(item['reference']['score_rate'])
                self.assertIsNone(item['relay']['score_rate'])
        class Failed(CorrectClient):
            def complete(self, case): raise EndpointError('network_error')
        failed, _ = self.collect(manifest, 'healthy', Failed)
        failed_diagnostic = calibration.evaluate(manifest, [failed])['scenarios']['healthy']['pilot_diagnostics']
        self.assertEqual((failed_diagnostic['evidence_state'], failed_diagnostic['completed_trials']), ('available', 0))
        self.assertEqual(sum(item['unknown_pairs'] for item in failed_diagnostic['templates']), 120)
        self.assertTrue(all(item['observed_score_gap'] is None for item in failed_diagnostic['templates']))

    def test_exam_pilot_diagnostics_report_missing_legacy_evidence_without_imputation(self):
        manifest = self.plan(scope='extended')
        full, _ = self.collect(manifest, 'healthy', CorrectClient)
        legacy = {key: value for key, value in full.items() if key != 'pilot_items'}
        with patch('relay_auditor.planning.exam_plan', side_effect=BudgetExceeded()):
            empty, _ = self.collect(manifest, 'healthy', CorrectClient, index=1)
        unavailable = calibration.evaluate(manifest, [legacy, empty])
        diagnostic = unavailable['scenarios']['healthy']['pilot_diagnostics']
        self.assertEqual(diagnostic, {
            'schema_version': 1, 'evidence': 'descriptive_pilot', 'evidence_state': 'unavailable',
            'pilot_trials': 2, 'item_evidence_trials': 0, 'missing_item_evidence_trials': 2,
            'completed_trials': 1, 'cancelled_trials': 0, 'templates': [],
        })
        self.assertEqual(unavailable['scenarios']['healthy']['pilot_usage']['requests'], 240)
        partial = calibration.evaluate(manifest, [full, empty])
        diagnostic = partial['scenarios']['healthy']['pilot_diagnostics']
        self.assertEqual((diagnostic['evidence_state'], diagnostic['item_evidence_trials'],
                          diagnostic['missing_item_evidence_trials']), ('partial', 1, 1))
        self.assertEqual(sum(item['planned_pairs'] for item in diagnostic['templates']), 120)
        self.assertEqual(partial['candidate_pass'], unavailable['candidate_pass'])
        self.assertEqual(partial['scenarios']['healthy']['pilot_usage'], unavailable['scenarios']['healthy']['pilot_usage'])
        self.assertEqual(unavailable['scenarios']['substitution']['pilot_diagnostics']['evidence_state'], 'unavailable')
        context = unavailable['scenarios']['context_truncated']['pilot_diagnostics']
        self.assertEqual(context['evidence_state'], 'not_applicable')
        self.assertEqual((context['templates'], context['item_evidence_trials'], context['missing_item_evidence_trials']), ([], 0, 0))
        assessment = calibration.freeze('gpt-primary', 'gpt-alternative', Protocol(), seed=42)
        assessment_row, _ = self.collect(assessment, 'healthy', CorrectClient)
        diagnostic = calibration.evaluate(assessment, [assessment_row])['scenarios']['healthy']['pilot_diagnostics']
        self.assertEqual((diagnostic['evidence_state'], diagnostic['templates'], diagnostic['pilot_trials'],
                          diagnostic['item_evidence_trials'], diagnostic['missing_item_evidence_trials']),
                         ('not_applicable', [], 1, 0, 0))

    def test_calibration_report_is_read_only_with_additive_pilot_diagnostics(self):
        from relay_auditor import cli
        manifest = self.plan()
        row, _ = self.collect(manifest, 'healthy', CorrectClient)
        with tempfile.TemporaryDirectory() as folder:
            study_id = manifest['manifest_hash'][:32]
            directory = Path(folder) / 'studies' / study_id
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (directory / 'outcomes.json').write_text(json.dumps([row]), encoding='utf-8')
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            output = io.StringIO()
            with patch.object(cli, 'data_directory', return_value=Path(folder)), \
                 patch.object(cli, 'Auditor', side_effect=AssertionError('private_profiles_loaded')), \
                 patch('relay_auditor.calibration_cli.hidden', side_effect=AssertionError('credential_prompt')), \
                 patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('api_client_constructed')), \
                 redirect_stdout(output), redirect_stderr(io.StringIO()):
                status = cli.main(['calibration-report', '--study-id', study_id])
            self.assertEqual(status, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['schema_version'], 2)
            self.assertFalse(report['candidate_pass'])
            scenario = report['scenarios']['healthy']
            self.assertTrue({'pilot_tasks', 'pilot_templates', 'pilot_usage', 'pilot_diagnostics'} <= scenario.keys())
            self.assertEqual(scenario['pilot_diagnostics']['evidence_state'], 'available')
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

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
                answer = case.expected if self.target.model == manifest['primary_model'] else None
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
