"""Native family studies use synthetic HTTP, production adapters and local budgets."""
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from relay_auditor import calibration
from relay_auditor.official import restore_reference
from relay_auditor.protocol import Protocol
from relay_auditor.storage import BudgetExceeded, Store
from relay_auditor.transport import APIClient


SETTINGS = {
    'claude': ('anthropic', 'anthropic', 'https://api.anthropic.com/v1'),
    'gemini': ('gemini', 'google', 'https://generativelanguage.googleapis.com/v1beta'),
}


def wrong_answer(value):
    if isinstance(value, dict):
        key = next(iter(value))
        return dict(value) | {key: wrong_answer(value[key])}
    if isinstance(value, list):
        return [wrong_answer(value[0]), *value[1:]] if value else [0]
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, str):
        return value + '-synthetic-wrong'
    raise AssertionError('unexpected_synthetic_answer_type')


class Response(io.BytesIO):
    def __init__(self, payload, *, stream=False):
        raw = (''.join('data: ' + json.dumps(event) + '\n\n' for event in payload)
               if stream else json.dumps(payload))
        super().__init__(raw.encode())
        self.headers = {'Content-Type': 'text/event-stream' if stream else 'application/json'}


class NativeWire:
    """The only fake boundary is HTTP; request building and parsing remain real."""
    def __init__(self, test, *, failure=None, missing_usage=False):
        self.test = test
        self.failure = failure
        self.missing_usage = missing_usage
        self.calls = []

    def __call__(self, target):
        wire = self

        class Client:
            def complete(self, case):
                return APIClient(target, lambda request, timeout: wire.respond(target, case, request)).complete(case)

        return Client()

    def respond(self, target, case, request):
        test = self.test
        wire, _, origin = SETTINGS['claude' if target.protocol.wire_api == 'anthropic' else 'gemini']
        body = json.loads(request.data)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.calls.append((target.model, case.seed, body))
        test.assertEqual(request.method, 'POST')
        test.assertNotIn('authorization', headers)
        test.assertNotIn(target.api_key, request.full_url)
        if wire == 'anthropic':
            test.assertEqual(request.full_url, origin + '/messages')
            test.assertEqual(headers['x-api-key'], 'synthetic-native-key')
            test.assertEqual(headers['anthropic-version'], '2023-06-01')
            test.assertEqual(body, {'model': target.model, 'max_tokens': target.protocol.max_output_tokens,
                                    'stream': target.protocol.stream,
                                    'messages': [{'role': 'user', 'content': case.prompt}]})
        else:
            route = ':streamGenerateContent?alt=sse' if target.protocol.stream else ':generateContent'
            test.assertEqual(request.full_url, origin + '/models/' + target.model + route)
            test.assertEqual(headers['x-goog-api-key'], 'synthetic-native-key')
            test.assertEqual(body, {'contents': [{'role': 'user', 'parts': [{'text': case.prompt}]}],
                                    'generationConfig': {'maxOutputTokens': target.protocol.max_output_tokens}})
        failure = self.failure
        if failure == 'network_once' and len(self.calls) == 1:
            raise TimeoutError('synthetic-timeout')
        if failure == 'interrupted_once' and len(self.calls) > 1:
            failure = None
        answer = json.dumps({'answer': wrong_answer(case.expected) if target.model.endswith('-alternative')
                             else case.expected})
        usage = {} if self.missing_usage else (
            {'input_tokens': 4, 'cache_read_input_tokens': 3, 'cache_creation_input_tokens': 2,
             'output_tokens': 5} if wire == 'anthropic' else
            {'promptTokenCount': 9, 'cachedContentTokenCount': 3,
             'candidatesTokenCount': 2, 'thoughtsTokenCount': 3})
        if wire == 'anthropic':
            stop = 'max_tokens' if failure == 'output_limit' else 'end_turn'
            if target.protocol.stream:
                events = [{'type': 'message_start', 'message': {'usage': usage | {'output_tokens': 0}
                                                               if usage else {}}},
                          {'type': 'content_block_delta', 'delta': {'type': 'thinking_delta',
                                                                  'thinking': 'SYNTHETIC_DISCARDED_THOUGHT'}},
                          {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': answer}}]
                if failure not in ('interrupted_once', 'interrupted'):
                    events.extend([{'type': 'message_delta', 'delta': {'stop_reason': stop},
                                    'usage': {'output_tokens': 5} if usage else {}}, {'type': 'message_stop'}])
                return Response(events, stream=True)
            result = {'content': [{'type': 'text', 'text': answer}], 'usage': usage}
            if failure != 'incomplete':
                result['stop_reason'] = stop
            return Response(result)
        stop = 'MAX_TOKENS' if failure == 'output_limit' else 'STOP'
        candidate = {'content': {'parts': [{'text': 'SYNTHETIC_DISCARDED_THOUGHT', 'thought': True},
                                           {'text': answer}]}}
        if failure not in ('interrupted_once', 'interrupted', 'incomplete'):
            candidate['finishReason'] = stop
        if target.protocol.stream:
            return Response([{'usageMetadata': usage}, {'candidates': [candidate]}], stream=True)
        return Response({'candidates': [candidate], 'usageMetadata': usage})


class NativeFamilyCalibrationTests(unittest.TestCase):
    def plan(self, family, *, stream=False, cap=4096, samples=40):
        wire = SETTINGS[family][0]
        try:
            return calibration.freeze(f'{family}-primary', f'{family}-alternative',
                                      Protocol(wire_api=wire, stream=stream, max_output_tokens=cap),
                                      family=family, suite='assessment-v4', scope='primary', samples=samples, seed=42)
        except ValueError as error:
            self.fail(f'explicit native assessment study must freeze: {error}')

    def collect(self, manifest, scenario, fixture, *, limits=(1000, 10_000_000), exhaust_after=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        store.set_limits(*limits)
        protocol = Protocol(**manifest['protocol'])
        primary = restore_reference(manifest['official_preset'], 'synthetic-native-key',
                                    manifest['primary_model'], protocol)
        alternative = restore_reference(manifest['official_preset'], 'synthetic-native-key',
                                        manifest['alternative_model'], protocol)
        with ExitStack() as stack:
            stack.enter_context(patch('relay_auditor.controller.Service.wait_for_retry', return_value=None))
            if exhaust_after is not None:
                reserve = store.reserve

                def limited_reserve(*args, **kwargs):
                    if store.budget()['requests'] >= exhaust_after:
                        raise BudgetExceeded()
                    return reserve(*args, **kwargs)

                stack.enter_context(patch.object(store, 'reserve', side_effect=limited_reserve))
            row = calibration.collect_trial(manifest, scenario, 0, 'pilot', primary, alternative, store,
                                            client_factory=fixture, date='2026-11-12')
        calibration.checked_records(manifest, [row])
        return row, store

    def test_native_json_and_sse_studies_route_exact_settings_and_family_tasks(self):
        for family, expected_counts in (
            ('claude', {'document': 16, 'structured': 8, 'code': 8, 'tool_args': 8}),
            ('gemini', {'document': 8, 'constraints': 8, 'structured': 8, 'code': 8, 'tool_args': 8}),
        ):
            for stream, cap in ((False, 4096), (True, 8192)):
                with self.subTest(family=family, stream=stream):
                    manifest = self.plan(family, stream=stream, cap=cap)
                    self.assertEqual(manifest['official_preset'], SETTINGS[family][1])
                    self.assertEqual(manifest['official_base_url'], SETTINGS[family][2])
                    self.assertEqual(manifest['scenarios'], ['healthy', 'substitution'])
                    calibration.validate(manifest)
                    fixture = NativeWire(self)
                    row, store = self.collect(manifest, 'healthy', fixture)
                    self.assertEqual((row['valid_pairs'], row['regressions'], row['improvements']), (40, 0, 0))
                    self.assertTrue(row['complete'])
                    self.assertFalse(row['detected'])
                    self.assertEqual((row['requests'], row['reported_tokens'], row['unknown_usage']), (80, 1120, 0))
                    actual_counts = {}
                    for item in row['pilot_items']:
                        if item['source_kind'] == 'relay':
                            actual_counts[item['task_kind']] = actual_counts.get(item['task_kind'], 0) + 1
                    self.assertEqual(actual_counts, expected_counts)
                    self.assertEqual(store.usage()['reference_requests'], 80)
                    self.assertEqual(store.usage()['probe_requests'], 0)
                    self.assertEqual(store.budget()['held_requests'], 0)
                    report = calibration.evaluate(manifest, [row])
                    self.assertEqual(report['family'], family)
                    self.assertEqual(report['validation_state'], 'experimental')
                    self.assertFalse(report['candidate_pass'])
                    self.assertNotIn('SYNTHETIC_DISCARDED_THOUGHT', json.dumps(row))
                    self.assertNotIn('synthetic-native-key', json.dumps(row))

    def test_substitution_uses_same_native_family_with_independent_official_spend(self):
        for family in SETTINGS:
            with self.subTest(family=family):
                manifest = self.plan(family)
                fixture = NativeWire(self)
                row, store = self.collect(manifest, 'substitution', fixture)
                self.assertEqual((row['valid_pairs'], row['regressions'], row['improvements']), (40, 40, 0))
                self.assertEqual(row['alternative_calls'], 40)
                self.assertTrue(row['complete'])
                self.assertTrue(row['detected'])
                self.assertEqual(store.usage()['reference_requests'], 80)
                self.assertFalse(calibration.evaluate(manifest, [row])['candidate_pass'])

    def test_native_family_requires_explicit_primary_assessment_and_reviewed_settings(self):
        for family in SETTINGS:
            protocol = Protocol(wire_api=SETTINGS[family][0])
            base = {'family': family, 'suite': 'assessment-v4', 'scope': 'primary'}
            invalid = [({'suite': None}, protocol), ({'suite': 'exam-v2'}, protocol),
                       ({'scope': 'extended'}, protocol), ({}, replace(protocol, wire_api='chat')),
                       ({}, replace(protocol, wire_api='responses')),
                       ({}, replace(protocol, reasoning_effort='none')),
                       ({}, replace(protocol, reasoning_effort='high')),
                       ({}, replace(protocol, temperature=0))]
            for options, settings in invalid:
                with self.subTest(family=family, options=options, settings=settings):
                    with self.assertRaises(ValueError):
                        calibration.freeze(f'{family}-primary', f'{family}-alternative', settings,
                                           **(base | options))
            for primary, alternative in ((f'{family}-primary', 'gpt-alternative'),
                                          ('gpt-primary', f'{family}-alternative')):
                with self.subTest(family=family, primary=primary), self.assertRaises(ValueError):
                    calibration.freeze(primary, alternative, protocol, **base)

    def test_native_manifest_and_collection_reject_changed_family_settings(self):
        manifest = self.plan('claude')
        for changes in ({'family': 'gemini'}, {'official_preset': 'google'}, {'scope': 'extended'},
                        {'protocol': manifest['protocol'] | {'max_output_tokens': 8192}},
                        {'protocol': manifest['protocol'] | {'stream': True}}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'invalid_or_modified_study'):
                calibration.validate(manifest | changes)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        primary = restore_reference('anthropic', 'synthetic-native-key', 'claude-primary',
                                    Protocol(wire_api='anthropic', max_output_tokens=8192))
        alternative = replace(primary, model='claude-alternative')
        with self.assertRaisesRegex(ValueError, 'study_targets_mismatch'):
            calibration.collect_trial(manifest, 'healthy', 0, 'pilot', primary, alternative, store,
                                      client_factory=NativeWire(self), date='2026-11-12')
        self.assertEqual(store.budget()['requests'], 0)

    def test_native_retry_reuses_question_and_counts_unknown_network_usage(self):
        for family in SETTINGS:
            for failure in ('network_once', 'interrupted_once'):
                with self.subTest(family=family, failure=failure):
                    manifest = self.plan(family, stream=failure == 'interrupted_once')
                    fixture = NativeWire(self, failure=failure)
                    row, store = self.collect(manifest, 'healthy', fixture)
                    self.assertTrue(row['complete'])
                    self.assertEqual((row['requests'], row['retry_requests'], row['valid_pairs']), (81, 1, 40))
                    self.assertEqual(fixture.calls[0], fixture.calls[1])
                    self.assertEqual(row['unknown_usage'], 1 if failure == 'network_once' else 0)
                    self.assertEqual(store.usage()['reference_requests'], 81)
                    self.assertEqual(store.budget()['held_requests'], 0)

    def test_missing_usage_preserves_grades_and_unknown_spend(self):
        for family in SETTINGS:
            with self.subTest(family=family):
                manifest = self.plan(family)
                row, store = self.collect(manifest, 'healthy', NativeWire(self, missing_usage=True))
                self.assertTrue(row['complete'])
                self.assertEqual((row['reported_tokens'], row['unknown_usage']), (0, 80))
                self.assertEqual(store.budget()['unknown_usage_requests'], 80)
                self.assertFalse(calibration.evaluate(manifest, [row])['candidate_pass'])

    def test_output_limit_and_missing_finish_never_become_scored_or_passing_trials(self):
        for family in SETTINGS:
            for failure, stream in (('output_limit', False), ('output_limit', True),
                                    ('incomplete', False), ('interrupted', True)):
                with self.subTest(family=family, failure=failure, stream=stream):
                    manifest = self.plan(family, stream=stream)
                    row, store = self.collect(manifest, 'healthy', NativeWire(self, failure=failure))
                    self.assertFalse(row['complete'])
                    self.assertFalse(row['detected'])
                    self.assertEqual((row['valid_pairs'], row['regressions']), (0, 0))
                    self.assertTrue(all(item['correct'] is None for item in row['pilot_items']))
                    self.assertEqual(row['retry_requests'], 2 if failure == 'interrupted' else 0)
                    self.assertEqual(store.budget()['held_requests'], 0)
                    report = calibration.evaluate(manifest, [row])
                    self.assertFalse(report['candidate_pass'])
                    self.assertEqual(report['scenarios']['healthy']['pilot_trials'], 1)

    def test_prestart_budget_exhaustion_is_retained_without_api_calls_or_holds(self):
        for family in SETTINGS:
            with self.subTest(family=family):
                manifest = self.plan(family)
                fixture = NativeWire(self)
                row, store = self.collect(manifest, 'healthy', fixture, limits=(1, 1))
                self.assertEqual(row.get('stop_reason'), 'budget_exhausted')
                self.assertEqual(fixture.calls, [])
                self.assertEqual((row['requests'], row['response_count'], row['valid_pairs']), (0, 0, 0))
                self.assertFalse(row['complete'])
                self.assertFalse(row['cancelled'])
                self.assertTrue(all(item['attempts'] == 0 for item in row['pilot_items']))
                self.assertEqual((store.budget()['held_requests'], store.budget()['held_tokens']), (0, 0))
                report = calibration.evaluate(manifest, [row])
                self.assertEqual(report['scenarios']['healthy']['pilot_trials'], 1)
                self.assertFalse(report['candidate_pass'])

    def test_midtrial_budget_exhaustion_retains_paid_pairs_and_releases_holds(self):
        for family in SETTINGS:
            with self.subTest(family=family):
                manifest = self.plan(family)
                fixture = NativeWire(self)
                row, store = self.collect(manifest, 'healthy', fixture, exhaust_after=2)
                self.assertEqual(row.get('stop_reason'), 'budget_exhausted')
                self.assertEqual((row['requests'], row['response_count'], row['valid_pairs']), (2, 2, 1))
                self.assertEqual((row['reported_tokens'], row['unknown_usage'], row['retry_requests']), (28, 0, 0))
                self.assertEqual(len(fixture.calls), 2)
                self.assertEqual(sum(item['attempts'] for item in row['pilot_items']), 2)
                self.assertEqual(sum(item['correct'] is True for item in row['pilot_items']), 2)
                self.assertFalse(row['complete'])
                self.assertFalse(row['detected'])
                self.assertEqual(store.usage()['reference_requests'], 2)
                self.assertEqual((store.budget()['held_requests'], store.budget()['held_tokens']), (0, 0))
                self.assertFalse(calibration.evaluate(manifest, [row])['candidate_pass'])

    def test_optional_budget_stop_reason_rejects_private_or_contradictory_values(self):
        manifest = self.plan('claude')
        stopped, _ = self.collect(manifest, 'healthy', NativeWire(self), limits=(1, 1))
        legacy = dict(stopped)
        legacy.pop('stop_reason', None)
        legacy.pop('trial_failure', None)
        calibration.checked_records(manifest, [legacy])
        for reason in (None, '', 'arbitrary-private-text', 'network_error', [], {}):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [legacy | {'stop_reason': reason}])
        for change in ({'complete': True}, {'cancelled': True}, {'detected': True}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
                calibration.checked_records(manifest, [legacy | {'stop_reason': 'budget_exhausted'} | change])
        completed, _ = self.collect(manifest, 'healthy', NativeWire(self))
        self.assertNotIn('stop_reason', completed)
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            calibration.checked_records(manifest, [completed | {'stop_reason': 'budget_exhausted'}])


if __name__ == '__main__':
    unittest.main()
