"""Family-specific frozen studies and offline estimates use synthetic answers only."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from relay_auditor import calibration, cli
from relay_auditor.calibration_readiness import preview
from relay_auditor.official import restore_reference
from relay_auditor.protocol import Protocol
from relay_auditor.simulation import simulate
from relay_auditor.storage import Store
from relay_auditor.transport import APIClient, Completion, EndpointError
from test_native_family_calibration import NativeWire, Response


def wrong(value):
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, str):
        return value + '-incorrect'
    if isinstance(value, list):
        return [wrong(value[0]), *value[1:]] if value else [0]
    if isinstance(value, dict) and value:
        key = next(iter(value))
        return value | {key: wrong(value[key])}
    raise AssertionError('unexpected_synthetic_answer')


class NativeExamStudyTests(unittest.TestCase):
    def plan(self, samples=120, **options):
        arguments = dict(family='claude', suite='claude-exam-v1', samples=samples, seed=42)
        arguments.update(options)
        protocol = arguments.pop('protocol', Protocol(wire_api='anthropic', max_output_tokens=2048))
        try:
            return calibration.freeze('claude-primary', 'claude-alternative', protocol, **arguments)
        except ValueError:
            self.fail('registered native exam study must freeze without using an assessment fallback')

    def collect(self, manifest, scenario='healthy', *, failure=None, limits=(1000, 10_000_000), client_factory=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        store.set_limits(*limits)
        protocol = Protocol(**manifest['protocol'])
        primary = restore_reference(manifest['official_preset'], 'synthetic-native-key', manifest['primary_model'], protocol)
        alternative = restore_reference(manifest['official_preset'], 'synthetic-native-key', manifest['alternative_model'], protocol)
        calls = []

        class Client:
            def __init__(self, target):
                self.target = target

            def complete(self, case):
                calls.append((self.target.model, case.seed, self.target.protocol))
                if failure == 'retry_once' and len(calls) == 1 or failure == 'network_error':
                    raise EndpointError('network_error')
                if failure == 'cancel' and len(calls) == 5:
                    raise KeyboardInterrupt()
                answer = wrong(case.expected) if self.target.model.endswith('alternative') else case.expected
                return Completion(json.dumps({'answer': answer}), {'total_tokens': 12})

        with patch('relay_auditor.controller.Service.wait_for_retry', return_value=None):
            row = calibration.collect_trial(manifest, scenario, 0, 'pilot', primary, alternative, store,
                                            client_factory=Client if client_factory is None else client_factory,
                                            date='2026-11-12')
        calibration.checked_records(manifest, [row])
        return row, store, calls

    def test_freeze_preserves_selected_suite_seed_full_size_and_retry_reservations(self):
        for samples, requests, retries in ((120, 52800, 10560), (180, 79200, 15840)):
            with self.subTest(samples=samples):
                manifest = self.plan(samples)
                self.assertEqual((manifest['suite_version'], manifest['suite_selection'], manifest['seed']),
                                 ('claude-exam-v1', 'claude-exam-v1', 42))
                self.assertEqual((manifest['planned_requests'], manifest['planned_retry_requests']), (requests, retries))
                self.assertEqual(manifest['retry_policy']['max_retries_per_item'], 2)
                self.assertEqual(manifest['retry_policy']['max_retry_requests_per_trial'], samples * 2 // 5)
                self.assertEqual(manifest['scenarios'], ['healthy', 'substitution'])
                self.assertEqual(manifest['official_preset'], 'anthropic')
                self.assertIn('exam_registry', manifest['implementation_hashes'])
                calibration.validate(manifest)

    def test_healthy_and_substitution_collect_full_native_papers_with_descriptive_diagnostics(self):
        for samples in (120, 180):
            for scenario, regressions, detected, offset in (
                    ('healthy', 0, False, 0), ('substitution', samples, True, 10_000_000)):
                with self.subTest(samples=samples, scenario=scenario):
                    manifest = self.plan(samples)
                    row, store, calls = self.collect(manifest, scenario)
                    self.assertTrue(row['complete'])
                    self.assertEqual((row['suite_version'], row['valid_pairs'], row['regressions'], row['detected']),
                                     ('claude-exam-v1', samples, regressions, detected))
                    self.assertEqual((row['requests'], row['retry_requests'], row['reported_tokens']),
                                     (samples * 2, 0, samples * 24))
                    self.assertEqual({item['seed'] for item in row['pilot_items']},
                                     set(range(42 + offset, 42 + offset + samples)))
                    self.assertTrue(all(protocol == Protocol(wire_api='anthropic') for _, _, protocol in calls))
                    report = calibration.evaluate(manifest, [row])
                    diagnostics = report['scenarios'][scenario]['pilot_diagnostics']
                    self.assertEqual(diagnostics['evidence_state'], 'available')
                    self.assertEqual(sum(item['planned_pairs'] for item in diagnostics['templates']), samples)
                    self.assertEqual(sum(item['regressions'] for item in diagnostics['templates']), regressions)
                    self.assertFalse(report['candidate_pass'])
                    self.assertEqual((store.usage()['reference_requests'], store.budget()['held_requests']),
                                     (samples * 2, 0))

    def test_retry_reuses_frozen_question_and_keeps_unknown_usage(self):
        row, store, calls = self.collect(self.plan(), failure='retry_once')
        self.assertTrue(row['complete'])
        self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs'], row['unknown_usage']),
                         (241, 1, 120, 1))
        self.assertEqual(calls[0], calls[1])
        self.assertEqual((store.budget()['held_requests'], store.budget()['held_tokens']), (0, 0))

    def test_native_exam_json_and_sse_use_real_wire_adapters_for_both_paper_sizes(self):
        for samples in (120, 180):
            for stream in (False, True):
                for scenario in ('healthy', 'substitution'):
                    with self.subTest(samples=samples, stream=stream, scenario=scenario):
                        manifest = self.plan(samples, protocol=Protocol(wire_api='anthropic', stream=stream))
                        wire = NativeWire(self)
                        row, store, _ = self.collect(manifest, scenario, client_factory=wire)
                        self.assertTrue(row['complete'])
                        self.assertEqual((row['valid_pairs'], row['regressions'], row['requests']),
                                         (samples, samples if scenario == 'substitution' else 0, samples * 2))
                        self.assertEqual((row['reported_tokens'], row['unknown_usage']), (samples * 28, 0))
                        self.assertEqual(len(wire.calls), samples * 2)
                        serialized = json.dumps(row)
                        self.assertNotIn('synthetic-native-key', serialized)
                        self.assertNotIn('SYNTHETIC_DISCARDED_THOUGHT', serialized)
                        self.assertEqual(store.budget()['held_requests'], 0)

    def test_failure_cancel_and_budget_stop_preserve_partial_evidence_without_completing(self):
        for failure, limits, requests, retries, pairs, cancelled in (
                ('network_error', (1000, 10_000_000), 3, 2, 0, False),
                ('cancel', (1000, 10_000_000), 5, 0, 2, True),
                (None, (1, 1), 0, 0, 0, False)):
            with self.subTest(failure=failure, requests=requests):
                manifest = self.plan()
                row, store, calls = self.collect(manifest, failure=failure, limits=limits)
                self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs'], row['cancelled']),
                                 (requests, retries, pairs, cancelled))
                self.assertFalse(row['complete'])
                self.assertFalse(row['detected'])
                self.assertEqual(len(calls), requests)
                self.assertEqual((store.budget()['held_requests'], store.budget()['held_tokens']), (0, 0))
                if requests == 0:
                    self.assertEqual(row['stop_reason'], 'budget_exhausted')
                self.assertFalse(calibration.evaluate(manifest, [row])['candidate_pass'])

    def test_native_pilot_reconstruction_rejects_wrong_legal_metadata_and_missing_slots(self):
        manifest = self.plan()
        row, _, _ = self.collect(manifest)
        first = row['pilot_items'][0]
        other = next(item for item in row['pilot_items'] if item['template'] != first['template'])
        for change in ({'seed': 43}, {'difficulty': 3}, {'template': other['template']}):
            items = copy.deepcopy(row['pilot_items'])
            items[0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | {'pilot_items': items}])
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.checked_records(manifest, [row | {'pilot_items': row['pilot_items'][:-1]}])
        calibration.checked_records(manifest, [row | {'pilot_items': list(reversed(row['pilot_items']))}])

    def test_new_and_legacy_study_source_hashes_remain_strict(self):
        for manifest in (self.plan(), calibration.freeze('gpt-primary', 'gpt-alternative', Protocol(), seed=42)):
            modified = copy.deepcopy(manifest)
            modified['implementation_hashes']['exam_registry'] = '0' * 64
            modified['manifest_hash'] = calibration._digest({key: value for key, value in modified.items()
                                                            if key != 'manifest_hash'})
            with self.assertRaisesRegex(ValueError, 'invalid_or_modified_study'):
                calibration.evaluate(modified, [])
            old = copy.deepcopy(manifest)
            old['implementation_hashes'].pop('exam_registry', None)
            old['manifest_hash'] = calibration._digest({key: value for key, value in old.items() if key != 'manifest_hash'})
            with self.assertRaisesRegex(ValueError, 'invalid_or_modified_study'):
                calibration.validate(old)

    def test_readiness_uses_native_prompt_bound_without_shrinking_papers(self):
        for samples, requests, tokens in ((120, 288, 3022848), (180, 432, 4534272)):
            with self.subTest(samples=samples):
                report = preview(self.plan(samples), request_limit=requests, token_limit=tokens)
                self.assertEqual(report['suite_version'], 'claude-exam-v1')
                self.assertEqual(report['samples'], samples)
                self.assertEqual(report['budget']['state'], 'fits_supplied_limits')
                self.assertTrue(all(row['per_call'] == 10496 and row['estimated_tokens'] == tokens
                                    for row in report['per_trial']))
                short = preview(self.plan(samples), request_limit=requests - 1, token_limit=tokens - 1)
                self.assertEqual(short['budget']['state'], 'insufficient')
                self.assertTrue(all(row['request_gap'] == row['token_gap'] == 1
                                    for row in short['budget']['per_trial']))

    def test_cli_selects_native_suite_without_reading_private_state_or_building_clients(self):
        output = io.StringIO()
        with patch.object(cli, 'data_directory', side_effect=AssertionError('private_state_read')), \
             patch.object(cli, 'Store', side_effect=AssertionError('private_store_opened')), \
             patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('real_api_client')), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = cli.main(['calibration-plan', '--family', 'claude', '--suite', 'claude-exam-v1',
                               '--wire-api', 'anthropic', '--primary-model', 'claude-primary',
                               '--alternative-model', 'claude-alternative', '--samples', '180', '--seed', '42'])
        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertEqual((report['family'], report['suite_version'], report['samples']), ('claude', 'claude-exam-v1', 180))
        self.assertEqual((report['real_api_requests'], report['collection_authorized']), (0, False))

    def test_simulation_runs_native_exam_pipeline_and_selected_full_size_without_io(self):
        with patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('real_api_client')):
            for samples in (120, 180):
                with self.subTest(samples=samples):
                    report = simulate(suite='claude-exam-v1', family='claude', samples=samples, trials=1, seed=42)
                    self.assertEqual((report['family'], report['suite_version'], report['real_api_requests']),
                                     ('claude', 'claude-exam-v1', 0))
                    self.assertEqual({row['pairs'] for row in report['paired']}, {samples})
                    stable = report['no_reference']['stable']
                    self.assertEqual(stable['pipeline'], 'run_exam')
                    self.assertEqual([row['correct'] for row in stable['rounds']],
                                     [samples, samples * 9 // 10, samples, samples * 9 // 10])
                    self.assertTrue(all(row['submitted'] for row in stable['rounds']))
                    self.assertFalse(report['no_reference']['one_failed_round']['rounds'][-1]['submitted'])

    def test_cross_family_versions_and_unreviewed_native_controls_never_fallback(self):
        for family, suite in (('claude', 'exam-v2'), ('gpt', 'claude-exam-v1'), ('deepseek', 'claude-exam-v1')):
            with self.subTest(family=family, suite=suite):
                with self.assertRaises(ValueError):
                    calibration.freeze(f'{family}-primary', f'{family}-alternative', Protocol(), family=family, suite=suite)
                with self.assertRaises(ValueError):
                    simulate(family=family, suite=suite, trials=1)
        for options in ({'scope': 'extended'}, {'samples': 40}, {'suite': None},
                        {'protocol': Protocol(wire_api='anthropic', temperature=0)}):
            arguments = dict(family='claude', suite='claude-exam-v1', samples=120)
            arguments.update(options)
            protocol = arguments.pop('protocol', Protocol(wire_api='anthropic'))
            with self.subTest(options=options), self.assertRaises(ValueError):
                calibration.freeze('claude-primary', 'claude-alternative', protocol, **arguments)

    def test_reviewed_native_exam_parameters_freeze_and_reach_the_real_adapter(self):
        protocol = Protocol(wire_api='anthropic', reasoning_effort='high', max_output_tokens=8192)
        try:
            manifest = calibration.freeze('claude-sonnet-4-6', 'claude-opus-4-6', protocol,
                                          family='claude', suite='claude-exam-v1', samples=120, seed=42)
        except ValueError:
            self.fail('reviewed native exam parameters must not inherit old assessment-only restrictions')
        self.assertEqual(manifest['protocol']['reasoning_effort'], 'high')
        self.assertEqual(manifest['scope'], 'primary')
        calls = []
        test = self

        def factory(target):
            class Client:
                def complete(self, case):
                    def respond(request, timeout):
                        body = json.loads(request.data)
                        test.assertEqual(body['thinking'], {'type': 'adaptive'})
                        test.assertEqual(body['output_config'], {'effort': 'high'})
                        test.assertEqual(body['max_tokens'], 8192)
                        test.assertNotIn('temperature', body)
                        calls.append(body['model'])
                        return Response({'content': [{'type': 'text', 'text': json.dumps({'answer': case.expected})}],
                                         'stop_reason': 'end_turn',
                                         'usage': {'input_tokens': 6, 'output_tokens': 6}})
                    return APIClient(target, respond).complete(case)
            return Client()

        row, store, _ = self.collect(manifest, 'substitution', client_factory=factory)
        self.assertEqual((row['complete'], row['requests'], row['valid_pairs']), (True, 240, 120))
        self.assertEqual(set(calls), {'claude-sonnet-4-6', 'claude-opus-4-6'})
        self.assertEqual(store.budget()['held_requests'], 0)

    def test_native_exam_support_is_exact_while_old_native_assessment_stays_default_only(self):
        for effort, temperature in (('none', 1), ('max', 1), ('xhigh', 1), ('high', None)):
            with self.subTest(effort=effort, temperature=temperature):
                protocol = Protocol(wire_api='anthropic', reasoning_effort=effort, temperature=temperature)
                try:
                    manifest = calibration.freeze('claude-opus-4-7', 'claude-opus-4-8', protocol,
                                                  family='claude', suite='claude-exam-v1', seed=42)
                except ValueError:
                    self.fail('exact reviewed native exam controls must be accepted')
                self.assertEqual(manifest['protocol']['temperature'], temperature)
                self.assertEqual(manifest['protocol']['reasoning_effort'], effort)
                with self.assertRaises(ValueError):
                    calibration.freeze('claude-opus-4-7', 'claude-opus-4-8', protocol,
                                       family='claude', suite='assessment-v4', seed=42)
        for primary, alternative, protocol in (
                ('claude-primary', 'claude-alternative', Protocol(wire_api='anthropic', reasoning_effort='high')),
                ('claude-haiku-4-5', 'claude-sonnet-4-5', Protocol(wire_api='anthropic', reasoning_effort='high')),
                ('claude-opus-4-6', 'claude-sonnet-4-6', Protocol(wire_api='anthropic', reasoning_effort='high', temperature=0))):
            with self.subTest(primary=primary), self.assertRaisesRegex(ValueError, 'invalid_study_model'):
                calibration.freeze(primary, alternative, protocol, family='claude', suite='claude-exam-v1')


class GeminiExamStudyTests(unittest.TestCase):
    collect = NativeExamStudyTests.collect

    def plan(self, samples=120, **options):
        arguments = dict(family='gemini', suite='gemini-exam-v1', samples=samples, seed=42)
        arguments.update(options)
        protocol = arguments.pop('protocol', Protocol(wire_api='gemini'))
        try:
            return calibration.freeze('gemini-primary', 'gemini-alternative', protocol, **arguments)
        except ValueError:
            self.fail('registered Gemini exam study must retain its independent paper')

    def test_gemini_native_json_and_sse_keep_full_papers_and_exact_pilot_metadata(self):
        for samples in (120, 180):
            for stream in (False, True):
                for scenario in ('healthy', 'substitution'):
                    with self.subTest(samples=samples, stream=stream, scenario=scenario):
                        manifest = self.plan(samples, protocol=Protocol(wire_api='gemini', stream=stream))
                        self.assertEqual((manifest['suite_selection'], manifest['suite_version'], manifest['seed']),
                                         ('gemini-exam-v1', 'gemini-exam-v1', 42))
                        self.assertEqual(manifest['retry_policy']['max_retry_requests_per_trial'], samples * 2 // 5)
                        self.assertTrue({'exam_registry', 'native_exam_generators', 'model_capabilities'}
                                        <= manifest['implementation_hashes'].keys())
                        fixture = NativeWire(self)
                        row, store, _ = self.collect(manifest, scenario, client_factory=fixture)
                        self.assertEqual((row['complete'], row['valid_pairs'], row['regressions'], row['detected']),
                                         (True, samples, samples if scenario == 'substitution' else 0,
                                          scenario == 'substitution'))
                        self.assertEqual((row['requests'], row['reported_tokens'], row['unknown_usage']),
                                         (samples * 2, samples * 28, 0))
                        self.assertEqual(row['suite_version'], 'gemini-exam-v1')
                        offset = 10_000_000 if scenario == 'substitution' else 0
                        self.assertEqual({item['seed'] for item in row['pilot_items']},
                                         set(range(42 + offset, 42 + offset + samples)))
                        report = calibration.evaluate(manifest, [row])
                        diagnostic = report['scenarios'][scenario]['pilot_diagnostics']
                        self.assertEqual(diagnostic['evidence_state'], 'available')
                        self.assertEqual(sum(item['planned_pairs'] for item in diagnostic['templates']), samples)
                        self.assertFalse(report['candidate_pass'])
                        self.assertEqual((store.usage()['reference_requests'], store.budget()['held_requests']),
                                         (samples * 2, 0))
                        self.assertNotIn('SYNTHETIC_DISCARDED_THOUGHT', json.dumps(row))

    def test_gemini_retry_cancel_and_budget_stops_preserve_evidence_and_release_holds(self):
        for failure, limits, requests, retries, valid, cancelled in (
                ('retry_once', (1000, 10_000_000), 241, 1, 120, False),
                ('network_error', (1000, 10_000_000), 3, 2, 0, False),
                ('cancel', (1000, 10_000_000), 5, 0, 2, True),
                (None, (1, 1), 0, 0, 0, False)):
            with self.subTest(failure=failure, requests=requests):
                manifest = self.plan()
                row, store, calls = self.collect(manifest, failure=failure, limits=limits)
                self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs'], row['cancelled']),
                                 (requests, retries, valid, cancelled))
                self.assertEqual(row['complete'], failure == 'retry_once')
                self.assertFalse(row['detected'])
                self.assertEqual(len(calls), requests)
                if failure == 'retry_once':
                    self.assertEqual(calls[0], calls[1])
                self.assertEqual((store.budget()['held_requests'], store.budget()['held_tokens']), (0, 0))
                self.assertFalse(calibration.evaluate(manifest, [row])['candidate_pass'])

    def test_gemini_native_interrupted_stream_retries_the_same_paper_slot(self):
        manifest = self.plan(protocol=Protocol(wire_api='gemini', stream=True))
        fixture = NativeWire(self, failure='interrupted_once')
        row, store, _ = self.collect(manifest, client_factory=fixture)
        self.assertEqual((row['complete'], row['requests'], row['retry_requests'], row['valid_pairs']),
                         (True, 241, 1, 120))
        self.assertEqual(fixture.calls[0], fixture.calls[1])
        self.assertEqual(store.budget()['held_requests'], 0)

    def test_gemini_pilot_validation_rejects_cross_paper_metadata_and_wrong_slots(self):
        manifest = self.plan()
        row, _, _ = self.collect(manifest)
        claude, _, _ = NativeExamStudyTests.collect(self, NativeExamStudyTests.plan(self))
        first = row['pilot_items'][0]
        other = next(item for item in row['pilot_items'] if item['template'] != first['template'])
        for change in ({'template': other['template']}, {'template': claude['pilot_items'][0]['template']},
                       {'seed': first['seed'] + 1}, {'difficulty': 3}):
            items = copy.deepcopy(row['pilot_items'])
            items[0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [row | {'pilot_items': items}])
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.checked_records(manifest, [row | {'pilot_items': row['pilot_items'][:-1]}])
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.checked_records(manifest, [row | {'suite_version': 'claude-exam-v1'}])

    def test_gemini_readiness_and_simulation_use_the_selected_full_size_and_prompt_bound(self):
        for samples, tokens in ((120, 3022848), (180, 4534272)):
            with self.subTest(samples=samples):
                manifest = self.plan(samples)
                report = preview(manifest)
                self.assertEqual(report['budget']['suggested_limits']['request_limit'], samples * 12 // 5)
                self.assertEqual(report['budget']['suggested_limits']['token_limit'], tokens)
                self.assertEqual({row['per_call'] for row in report['per_trial']}, {10496})
                simulation = simulate(family='gemini', suite='gemini-exam-v1', samples=samples, trials=1, seed=42)
                self.assertEqual((simulation['family'], simulation['suite_version'], simulation['real_api_requests']),
                                 ('gemini', 'gemini-exam-v1', 0))
                self.assertEqual({row['pairs'] for row in simulation['paired']}, {samples})
                self.assertEqual(simulation['no_reference']['stable']['pipeline'], 'run_exam')
                self.assertEqual([row['correct'] for row in simulation['no_reference']['stable']['rounds']],
                                 [samples, samples * 9 // 10, samples, samples * 9 // 10])
                self.assertFalse(simulation['no_reference']['one_failed_round']['rounds'][-1]['submitted'])

    def test_reviewed_gemini_exam_parameters_are_frozen_and_serialized_for_both_sides(self):
        protocol = Protocol(wire_api='gemini', reasoning_effort='high', temperature=.5, max_output_tokens=4096)
        try:
            manifest = calibration.freeze('gemini-3.1-pro-preview', 'gemini-3-flash-preview', protocol,
                                          family='gemini', suite='gemini-exam-v1', samples=120, seed=42)
        except ValueError:
            self.fail('reviewed Gemini exam parameters must freeze without falling back to defaults')
        calls = []
        test = self

        def factory(target):
            class Client:
                def complete(self, case):
                    def respond(request, timeout):
                        body = json.loads(request.data)
                        test.assertEqual(body['generationConfig'], {'maxOutputTokens': 4096,
                                                                  'thinkingConfig': {'thinkingLevel': 'HIGH'},
                                                                  'temperature': .5})
                        calls.append(target.model)
                        return Response({'candidates': [{'content': {'parts': [{'text': json.dumps({'answer': case.expected})}]},
                                                        'finishReason': 'STOP'}],
                                         'usageMetadata': {'promptTokenCount': 6, 'candidatesTokenCount': 4,
                                                           'thoughtsTokenCount': 2}})
                    return APIClient(target, respond).complete(case)
            return Client()

        row, store, _ = self.collect(manifest, 'substitution', client_factory=factory)
        self.assertEqual((row['complete'], row['requests'], row['valid_pairs']), (True, 240, 120))
        self.assertEqual(set(calls), {'gemini-3.1-pro-preview', 'gemini-3-flash-preview'})
        self.assertEqual((manifest['protocol']['reasoning_effort'], manifest['protocol']['temperature']), ('high', .5))
        self.assertEqual(store.budget()['held_requests'], 0)
        with self.assertRaises(ValueError):
            calibration.freeze('gemini-3.1-pro-preview', 'gemini-3-flash-preview', protocol,
                               family='gemini', suite='assessment-v4')

    def test_gemini_exam_rejects_unreviewed_effort_and_extended_scope(self):
        for primary, alternative, effort in (('gemini-primary', 'gemini-alternative', 'high'),
                                             ('gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'none'),
                                             ('gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'minimal')):
            with self.subTest(primary=primary, effort=effort), self.assertRaisesRegex(ValueError, 'invalid_study_model'):
                calibration.freeze(primary, alternative, Protocol(wire_api='gemini', reasoning_effort=effort),
                                   family='gemini', suite='gemini-exam-v1')
        with self.assertRaisesRegex(ValueError, 'invalid_study'):
            calibration.freeze('gemini-primary', 'gemini-alternative', Protocol(wire_api='gemini'),
                               family='gemini', suite='gemini-exam-v1', scope='extended')


class DeepSeekExamStudyControlTests(unittest.TestCase):
    collect = NativeExamStudyTests.collect

    def test_reviewed_deepseek_protocol_preserves_legacy_paper_and_full_substitution_control(self):
        protocol = Protocol(wire_api='deepseek', reasoning_effort='high', max_output_tokens=4096)
        test = self
        for samples in (120, 180):
            with self.subTest(samples=samples):
                manifest = calibration.freeze('deepseek-flash', 'deepseek-v4-pro', protocol,
                                              family='deepseek', suite='exam-v2', samples=samples, seed=42)
                calls = []

                def factory(target):
                    class Client:
                        def complete(self, case):
                            def respond(request, timeout):
                                body = json.loads(request.data)
                                test.assertEqual(body, {'model': target.model, 'stream': False,
                                                        'messages': [case.payload()], 'max_tokens': 4096,
                                                        'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'})
                                calls.append(target.model)
                                answer = case.expected if target.model == 'deepseek-flash' else wrong(case.expected)
                                return Response({'choices': [{'message': {'content': json.dumps({'answer': answer})},
                                                              'finish_reason': 'stop'}],
                                                 'usage': {'prompt_tokens': 6, 'completion_tokens': 6}})
                            return APIClient(target, respond).complete(case)
                    return Client()

                row, store, _ = self.collect(manifest, 'substitution', client_factory=factory)
                self.assertEqual((row['suite_version'], row['complete'], row['valid_pairs'], row['regressions']),
                                 ('exam-v2', True, samples, samples))
                self.assertTrue(row['detected'])
                self.assertEqual(set(calls), {'deepseek-flash', 'deepseek-v4-pro'})
                self.assertEqual((row['requests'], row['reported_tokens']), (samples * 2, samples * 24))
                self.assertFalse(any(item['template'].startswith(('claude_', 'gemini_')) for item in row['pilot_items']))
                self.assertEqual(store.budget()['held_requests'], 0)


if __name__ == '__main__':
    unittest.main()
