import json
import tempfile
import unittest
from unittest.mock import patch

from relay_auditor.assessment import assessment_cases
from relay_auditor.controller import Service
from relay_auditor.exporting import html_report
from relay_auditor.planning import ASSESSMENT_PROMPT_BYTES
from relay_auditor.reports import explain, trend
from relay_auditor.profiles import Profiles
from relay_auditor.protocol import Protocol, make_case
from relay_auditor.suites import cases, quality_case
from relay_auditor.storage import Store
from relay_auditor.transport import APIClient, Completion, EndpointError, Target
from test_sdk_exports import FakeVault
from test_service import FakeClient
from test_transport import Response


class SimulatedClient(FakeClient):
    def complete(self, case):
        if self.target.role == 'official_api' and case.kind == 'repair':
            return Completion('', complete=False, issue='output_limit')
        if self.target.role == 'relay' and self.target.model.startswith('deepseek-') and case.kind == 'constraints_multi':
            return Completion('{"answer":[]}')
        return super().complete(case)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.addCleanup(self.store.close)
        self.service = Service(self.store, client_factory=SimulatedClient)
        self.deepseek = Protocol(wire_api='deepseek')

    def test_transient_failure_retries_the_same_question_on_only_the_failed_side(self):
        calls = []
        class InterruptedClient(FakeClient):
            def complete(self, case):
                key = (self.target.role, case.seed)
                calls.append(key)
                if key == ('relay', 43):
                    if calls.count(key) == 1:
                        return Completion('synthetic fragment', complete=False, issue='stream_interrupted')
                    if calls.count(key) == 2:
                        raise EndpointError('network_error')
                return super().complete(case)
        self.service.client_factory = InterruptedClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test', reference_key='synthetic-ref')
        with patch('relay_auditor.assessment.RETRY_DELAYS', (0, 0), create=True):
            result = self.service.run(alias, 'assessment', samples=3, seed=42)
        self.assertEqual(calls, [('relay', 42), ('reference', 42), ('reference', 43), ('relay', 43),
                                 ('relay', 43), ('relay', 43), ('relay', 44), ('reference', 44)])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['paired_result']['valid_pairs'], 3)
        self.assertEqual(result['retry_requests'], 2)
        self.assertEqual(result['capability_attempted'], 3)
        self.assertEqual(self.store.usage()['probe_requests'], 5)
        self.assertEqual(self.store.usage()['reference_requests'], 3)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_persistent_disconnect_stops_run_and_keeps_prior_scores(self):
        calls = []
        class BrokenClient(FakeClient):
            def complete(self, case):
                calls.append(case.seed)
                if case.seed == 43:
                    raise EndpointError('network_error')
                return super().complete(case)
        self.service.client_factory = BrokenClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        with patch('relay_auditor.assessment.RETRY_DELAYS', (0, 0), create=True):
            result = self.service.run(alias, 'assessment', samples=4, seed=42)
        self.assertEqual(calls, [42, 43, 43, 43])
        self.assertEqual((result['status'], result['error_code'], result['failure_source']), ('unavailable', 'network_error', 'relay'))
        self.assertEqual((result['capability_valid'], result['capability_correct'], result['retry_requests']), (1, 1, 2))
        self.assertIn('连续', explain(result)['headline'])
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_retry_cannot_use_reserved_budget_for_later_questions(self):
        class BrokenClient(FakeClient):
            def complete(self, case):
                return Completion('', complete=False, issue='stream_interrupted')
        self.service.client_factory = BrokenClient
        self.store.set_limits(2, 100000)
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        self.assertEqual(self.service.estimate(alias, 'assessment', 2)['max_retry_requests'], 4)
        with patch('relay_auditor.assessment.RETRY_DELAYS', (0, 0), create=True):
            result = self.service.run(alias, 'assessment', samples=2, seed=42)
        self.assertEqual((result['status'], result['failure_source'], result['retry_requests']), ('budget_exhausted', 'relay', 0))
        self.assertEqual(self.store.budget()['requests'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_cancel_while_waiting_for_retry_sends_no_more_requests(self):
        class InterruptedClient(FakeClient):
            def complete(self, case):
                raise EndpointError('network_error')
        self.service.client_factory = InterruptedClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        monitor = self.service.monitors[alias]
        with patch.object(monitor.cancel, 'wait', return_value=True) as wait:
            result = self.service.run(alias, 'assessment', samples=3, seed=42)
        wait.assert_called_once_with(1)
        self.assertEqual((result['status'], result['retry_requests']), ('cancelled', 0))
        self.assertEqual(self.store.budget()['requests'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_authentication_failure_stops_without_retrying(self):
        class InvalidKeyClient(FakeClient):
            def complete(self, case):
                if self.target.role == 'reference':
                    raise EndpointError('authentication_failed')
                return super().complete(case)
        self.service.client_factory = InvalidKeyClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test', reference_key='synthetic-ref')
        result = self.service.run(alias, 'assessment', samples=3, seed=42)
        self.assertEqual((result['status'], result['error_code'], result['failure_source'], result['retry_requests']),
                         ('unavailable', 'authentication_failed', 'reference', 0))
        self.assertEqual((self.store.usage()['probe_requests'], self.store.usage()['reference_requests']), (1, 1))

    def test_scheduled_detection_keeps_its_original_request_budget(self):
        class InterruptedClient(FakeClient):
            def complete(self, case):
                return Completion('', complete=False, issue='stream_interrupted')
        self.service.client_factory = InterruptedClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        self.service.control(alias, enabled=True, active_only=False)
        with patch('relay_auditor.controller.threading') as scheduler:
            self.service.submit(alias, 'assessment', samples=3, automatic=True)
        worker = scheduler.Thread.call_args.kwargs
        worker['target'](*worker['args'])
        result = self.service.monitors[alias].last_result
        self.assertEqual((result['status'], result['retry_requests']), ('ok', 0))
        self.assertEqual(self.store.budget()['requests'], 3)

    def test_model_family_is_independent_of_protocol_and_no_key_still_gives_capability(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'claude-test', Protocol(wire_api='chat'))
        plan = self.service.estimate(alias, 'assessment')
        self.assertEqual(plan['required_requests'], 10)
        self.assertEqual((plan['target_requests'], plan['reference_requests']), (10, 0))
        result = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual(result['model_family'], 'claude')
        self.assertIn('document', [row['task_kind'] for row in result['assessment_tasks']])
        self.assertEqual(result['capability_correct'], 10)
        self.assertEqual(result['identity_state'], 'not_tested')
        self.assertEqual(self.service.ui_snapshot()['report_cards'][alias]['headline'], '本轮能力体检')

    def test_direct_deepseek_has_distinct_accounting_and_diagnosis(self):
        alias = self.service.configure('https://api.deepseek.com/v1', 'synthetic', 'deepseek-v4-flash', self.deepseek)
        result = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual(result['source_kind'], 'official_api')
        self.assertEqual(result['capability_correct'], 3)
        self.assertEqual((result['status'], result['error_code'], result['retry_requests']), ('unavailable', 'output_limit', 0))
        self.assertEqual(result['response_issues'], [{'source_kind':'official_api', 'error_code':'output_limit', 'sample_count':1}])
        usage = self.store.usage()
        self.assertEqual(usage['probe_requests'], 0)
        self.assertEqual(usage['direct_probe_requests'], 4)
        self.assertIn('输出达到上限', self.service.ui_snapshot()['report_cards'][alias]['diagnostics'][0])
        self.assertEqual(result['assessment_counts'], [
            {'source_kind': 'official_api', 'sample_count': 10, 'attempted': 4, 'response_count': 4,
             'valid': 3, 'correct': 3}])
        self.assertIn('无法评分 1', self.service.ui_snapshot()['report_cards'][alias]['capability'])

    def test_matching_official_reference_produces_counts_but_abstains_on_small_sample(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'deepseek-flash', self.deepseek,
                                       reference_key='synthetic-reference')
        self.assertEqual(self.service.monitors[alias].reference.base_url, 'https://api.deepseek.com')
        self.assertEqual(self.service.estimate(alias, 'assessment')['required_requests'], 20)
        result = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual(result['paired_result']['reference_correct'], 10)
        self.assertEqual(result['paired_result']['target_correct'], 6)
        self.assertEqual(result['identity_state'], 'not_tested')
        self.assertEqual(result['suite_version'], 'assessment-v3')
        self.assertIsNone(result.get('audit_index'))
        self.assertEqual(self.store.next_audit()[0], 1)
        reasoning = [row for row in result['assessment_tasks'] if row['task_kind'] == 'constraints_multi']
        self.assertEqual(sum(row['reference_correct'] for row in reasoning), 4)
        self.assertEqual(sum(row['target_correct'] for row in reasoning), 0)
        brief = self.service.ui_snapshot()['report_cards'][alias]
        self.assertIn('证据不足', brief['headline'])
        self.assertIn('答对 6，答错 4', brief['capability'])
        self.assertEqual(result['assessment_counts'][1]['source_kind'], 'reference')
        legacy_counts = [result['assessment_counts'][0], result['assessment_counts'][1] | {'source_kind': None}]
        self.assertIn('答对 6，答错 4', explain(result | {'assessment_counts': legacy_counts})['capability'])
        self.assertIn('中转 6/10', brief['comparison'])
        self.assertIn('官方 10/10', html_report(self.service.snapshot()))

    def test_v3_family_tasks_are_bounded_and_repeatable(self):
        schedules = {'gpt-test': {'code_branch', 'repair_edges'}, 'deepseek-flash': {'constraints_multi'}}
        for model, expected in schedules.items():
            first = list(assessment_cases(model, 200, 42))
            self.assertEqual(first, list(assessment_cases(model, 200, 42)))
            self.assertTrue(expected <= {case.kind for case, _ in first})
            self.assertTrue(all(len(case.prompt.encode()) <= ASSESSMENT_PROMPT_BYTES for case, _ in first))
            self.assertTrue(all(case.grade(json.dumps({'answer': case.expected}))['correct'] for case, _ in first))
        gpt_kinds = {case.kind for case, _ in assessment_cases('gpt-test', 10, 42)}
        self.assertTrue({'code', 'repair'}.isdisjoint(gpt_kinds))
        self.assertTrue({'code', 'repair', 'constraints'} <= {case.kind for case in cases('quality')})

    def test_fenced_json_recovery_preserves_correctness_and_rejects_unsafe_salvage(self):
        class FormatClient(FakeClient):
            def complete(self, case):
                correct = json.dumps({'answer': case.expected})
                block = f'```json\n{correct}\n```'
                texts = (block, '```\n{"answer": []}\n```', f'Before\n{block}', f'{block}\nAfter', block, block + '\n' + block)
                index = case.seed - 42
                return Completion(texts[index], complete=index != 4)
        self.service.client_factory = FormatClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        result = self.service.run(alias, 'assessment', samples=6, seed=42)
        self.assertEqual(result['capability_valid'], 2)
        self.assertEqual(result['capability_correct'], 1)
        self.assertEqual(result['invalid_responses'], 4)
        self.assertEqual({row['error_code']: row['sample_count'] for row in result['response_issues']},
                         {'recovered_format': 2, 'answer_format': 3, 'incomplete_output': 1})

    def test_partial_pairs_bound_the_loss_using_each_known_answer(self):
        class PartialClient(FakeClient):
            def complete(self, case):
                reference = self.target.role == 'reference'
                if (case.seed == 42 and not reference) or (case.seed == 43 and reference):
                    return Completion('unscorable')
                if case.seed == 44 and not reference:
                    return Completion('{"answer":{}}')
                return super().complete(case)
        self.service.client_factory = PartialClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test',
                                       reference_key='synthetic-reference')
        result = self.service.run(alias, 'assessment', samples=3, seed=42)
        pair = result['paired_result']
        self.assertEqual((pair['planned_pairs'], pair['attempted_pairs'], pair['valid_pairs']), (3, 3, 1))
        self.assertEqual(pair['status'], 'incomplete_comparison')
        self.assertEqual(pair['accuracy_loss'], 1)
        self.assertEqual(pair['loss_bounds'], [0, 2/3])
        self.assertFalse(result['detected_anomaly'])
        self.assertIsNone(result.get('audit_index'))

    def test_cancelled_run_retains_actual_pair_count_and_bounds(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test',
                                       reference_key='synthetic-reference')
        monitor = self.service.monitors[alias]
        class CancelClient(FakeClient):
            def complete(self, case):
                monitor.cancel.set()
                return super().complete(case)
        self.service.client_factory = CancelClient
        result = self.service.run(alias, 'assessment', samples=3, seed=42)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['capability_attempted'], 1)
        pair = result['paired_result']
        self.assertEqual((pair['planned_pairs'], pair['attempted_pairs'], pair['valid_pairs']), (3, 1, 0))
        self.assertEqual(pair['loss_bounds'], [-1, 2/3])
        self.assertEqual(self.store.budget()['requests'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_presend_reference_failure_is_not_counted_as_a_request(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test',
                                       reference_key='synthetic-reference')
        call = self.service._call
        def blocked_reference(monitor, case, *, reference=False, batch=None):
            if reference:
                raise EndpointError('reference_required')
            return call(monitor, case, batch=batch)
        self.service._call = blocked_reference
        result = self.service.run(alias, 'assessment', samples=3, seed=42)
        self.assertEqual(self.store.budget()['requests'], 3)
        self.assertEqual(result['assessment_counts'][1]['attempted'], 0)
        self.assertEqual(result['network_failures'], 0)
        self.assertEqual(result['paired_result']['loss_bounds'], [-1, 0])

    def test_tool_argument_schema_and_grading_use_the_same_envelope(self):
        case = quality_case('tool_args', 1)
        self.assertIn('Return exactly {"answer":{"name":', case.prompt)
        self.assertEqual(case.prompt.count('Return exactly'), 1)
        self.assertTrue(case.grade(json.dumps({'answer': case.expected}))['correct'])

    def test_history_requires_persistent_drop_across_new_seed_rounds(self):
        common = {'target_id': 'a' * 32, 'status': 'ok', 'suite_version': 'assessment-v2', 'mode': 'assessment',
                  'model': 'gpt-test', 'sample_count': 10, 'capability_completed': 10, 'capability_valid': 10}
        rows = [common | {'evaluated_at': f'2026-11-05T00:00:0{i}+00:00', 'task_seed': i, 'capability_correct': score}
                for i, score in enumerate((10, 10, 8, 9))]
        self.assertEqual(trend(rows[:3])['status'], 'insufficient_data')
        self.assertEqual(trend(rows)['status'], 'historical_decline_signal')
        replay = rows[-1] | {'task_seed': rows[-2]['task_seed']}
        self.assertEqual(trend(rows[:-1] + [replay])['status'], 'insufficient_data')
        recovered = rows[-1] | {'capability_correct': 10}
        self.assertEqual(trend(rows[:-1] + [recovered])['status'], 'no_detected_deviation')

    def test_mismatched_model_reference_is_never_called_by_default(self):
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'deepseek-v4-flash', self.deepseek,
                                       reference_key='synthetic-reference', reference_model='deepseek-v4-pro')
        result = self.service.run(alias, 'assessment', seed=42)
        self.assertEqual(result['reference_state'], 'reference_mismatch')
        self.assertEqual(self.store.usage()['reference_requests'], 0)

    def test_protocol_change_and_restart_keep_existing_reference_destination(self):
        profiles = Profiles(self.store.directory / 'synthetic-profiles', vault=FakeVault())
        service = Service(self.store, profiles=profiles)
        alias = service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol(wire_api='chat'),
                                  reference_key='synthetic-reference', save_credentials=True)
        service.update_target(alias, display_name='Synthetic', model='deepseek-flash', wire_api='deepseek')
        restored = Service(self.store, profiles=profiles)
        self.assertEqual(restored.monitors[alias].reference.base_url, 'https://api.openai.com/v1')
        self.assertFalse(restored.estimate(alias, 'assessment')['matched_reference'])
        restored.credentials(alias, None, reference_key='new-synthetic-reference')
        self.assertEqual(restored.monitors[alias].reference.base_url, 'https://api.deepseek.com')
        self.assertTrue(restored.estimate(alias, 'assessment')['matched_reference'])

    def test_deepseek_wire_payload_and_reason_codes(self):
        captured = []
        target = Target('https://api.deepseek.com', 'synthetic', 'deepseek-v4-flash',
                        Protocol(wire_api='deepseek', reasoning_effort='none'), role='reference')

        def open_request(request, **kwargs):
            captured.append(json.loads(request.data))
            return Response(b'{"choices":[{"message":{"reasoning_content":"synthetic-hidden","content":""},"finish_reason":"length"}]}')

        result = APIClient(target, open_request).complete(make_case('digit', 0))
        self.assertEqual(result.issue, 'output_limit')
        self.assertEqual(result.text, '')
        self.assertEqual(captured[0]['thinking'], {'type':'disabled'})
        self.assertIn('max_tokens', captured[0])
        self.assertNotIn('max_completion_tokens', captured[0])


if __name__ == '__main__':
    unittest.main()
