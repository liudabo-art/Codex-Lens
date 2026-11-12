import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from relay_auditor.controller import Cancelled, Service
from relay_auditor.exam import EXAM_FAMILIES, EXAM_MAX_PROMPT_BYTES, EXAM_SIZES, EXAM_TASKS, exam_cases, run_exam
from relay_auditor.storage import BudgetExceeded, Store
from relay_auditor.transport import Completion, EndpointError


class ExamPaperTests(unittest.TestCase):
    def test_every_block_has_balanced_unique_variants_and_reproducible_answers(self):
        for family in EXAM_FAMILIES:
            for samples in EXAM_SIZES:
                with self.subTest(family=family, samples=samples):
                    paper = tuple(exam_cases(family, samples, 42))
                    self.assertEqual(paper, tuple(exam_cases(family, samples, 42)))
                    self.assertNotEqual(paper, tuple(exam_cases(family, samples, 43)))
                    self.assertEqual(len({case.item_id for case, _ in paper}), samples)
                    self.assertEqual(len({case.prompt for case, _ in paper}), samples)
                    self.assertTrue(all(len(case.prompt.encode()) <= EXAM_MAX_PROMPT_BYTES for case, _ in paper))
                    self.assertTrue(all(case.grade(json.dumps({'answer': case.expected}))['correct'] for case, _ in paper))
                    for start in range(0, samples, 60):
                        block = paper[start:start + 60]
                        counts = Counter((case.kind, difficulty) for case, difficulty in block)
                        self.assertEqual(counts, {(kind, difficulty): 4 for kind in EXAM_TASKS for difficulty in (1, 2, 3)})
                        variants = Counter((case.kind, difficulty, case.variant) for case, difficulty in block)
                        self.assertEqual(len(variants), 60)
                        self.assertTrue(all(count == 1 for count in variants.values()))

    def test_unsupported_families_and_paper_lengths_cannot_generate_papers(self):
        for family, samples in [('claude', 120), ('gpt', 10), ('deepseek', 200)]:
            with self.assertRaises(ValueError):
                tuple(exam_cases(family, samples, 42))


class ExamExecutionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name))
        self.addCleanup(self.store.close)
        self.store.set_limits(1000, 10_000_000)
        self.calls = []
        self.outcome = None
        self.service = Service(self.store, client_factory=lambda target: Client(self, target))
        self.addCleanup(self.service.stop)
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test',
                                       reference_key='synthetic-reference')
        self.monitor = self.service.monitors[alias]
        self.service.wait_for_retry = lambda monitor, seconds: None

    def run_paper(self, *, paired=False, samples=120):
        requests = samples * (2 if paired else 1)
        plan = {
            'comparison': 'paired' if paired else 'relay_only',
            'sample_count': samples,
            'required_requests': requests,
            'max_retry_requests': requests // 5,
            'max_requests': requests * 6 // 5,
            'estimated_tokens': requests * 6 // 5 * 6400,
            'per_call': 6400,
        }
        return run_exam(self.service, self.monitor, plan, self.result, seed=42)

    def test_full_single_side_counts_wrong_and_format_failures_and_recovers_fence(self):
        self.result = {}
        def outcome(role, case, attempt, call_number):
            if call_number == 1:
                return Completion('a malformed complete answer')
            if call_number == 2:
                return Completion('{"answer":null}')
            if call_number == 3:
                fence = chr(96) * 3
                body = json.dumps({'answer': case.expected})
                return Completion(f'{fence}json\n{body}\n{fence}')
            if call_number == 4:
                def mutate(value):
                    if type(value) is int:
                        return value + 999
                    if type(value) is str:
                        return value + '_wrong'
                    if type(value) is bool:
                        return not value
                    if isinstance(value, list):
                        return [mutate(item) for item in value]
                    return {key: mutate(item) for key, item in value.items()}
                wrong = mutate(case.expected)
                return Completion(json.dumps({'answer': wrong}))
            return None
        self.outcome = outcome
        result = self.run_paper()
        self.assertTrue(result['exam']['submitted'])
        side, = result['exam']['sides']
        self.assertEqual((side['completed'], side['correct'], side['format_recovered']), (120, 117, 1))
        self.assertEqual(side['format_failures'], 2)
        self.assertNotIn('paired_result', result)
        self.assertEqual(len(self.calls), 120)
        self.assertEqual(self.store.budget()['held_requests'], 0)
        self.assertEqual(self.store.budget()['requests'], 120)

    def test_item_diagnostics_are_anonymous_and_preserve_format_failures(self):
        self.result = {}
        def outcome(role, case, attempt, index):
            if index == 1:
                return Completion('Explanation then ' + json.dumps({'answer': case.expected}))
            if index == 2:
                return Completion('{"answer":null}')
            return None
        self.outcome = outcome
        result = self.run_paper(paired=True)
        self.assertEqual(result['suite_version'], 'exam-v2')
        rows = result['item_results']
        self.assertEqual(len(rows), 240)
        first, second = rows[:2]
        self.assertEqual((first['question_number'], first['source_kind'], first['format_state'], first['attempts']),
                         (1, 'relay', 'recovered_format', 1))
        self.assertIsNone(second['correct'])
        self.assertEqual(second['error_code'], 'answer_format')
        self.assertEqual(result['paired_result']['valid_pairs'], 120)
        self.assertEqual(result['paired_result']['reference_correct'], 119)
        allowed = {'question_number', 'task_kind', 'template', 'difficulty', 'seed', 'source_kind',
                   'correct', 'format_state', 'attempts', 'error_code', 'grading_issue'}
        self.assertTrue(all(set(row) == allowed for row in rows))

    def test_paired_alternates_and_retries_only_the_failed_side_and_item(self):
        self.result = {}
        def outcome(role, case, attempt, call_number):
            if call_number == 2:
                return Completion('', complete=False, issue='stream_interrupted')
            if call_number == 3:
                return Completion('')
            return None
        self.outcome = outcome
        result = self.run_paper(paired=True, samples=180)
        self.assertTrue(result['exam']['submitted'])
        self.assertEqual([role for role, _ in self.calls[:6]], ['relay', 'reference', 'reference', 'reference', 'reference', 'relay'])
        self.assertEqual(len({case.item_id for _, case in self.calls[:4]}), 1)
        self.assertEqual(result['retry_requests'], 2)
        self.assertEqual(result['paired_result']['valid_pairs'], 180)
        self.assertEqual(result['audit_index'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)
        usage = self.store.usage()
        self.assertEqual((usage['probe_requests'], usage['reference_requests']), (180, 182))

    def test_official_retry_exhaustion_leaves_the_exam_unsubmitted(self):
        self.result = {}
        def outcome(role, case, attempt, call_number):
            if role == 'reference' and attempt <= 3:
                raise EndpointError('network_error')
            return None
        self.outcome = outcome
        with self.assertRaisesRegex(EndpointError, 'network_error'):
            self.run_paper(paired=True)
        self.assertFalse(self.result['exam']['submitted'])
        self.assertEqual((self.result['failure_source'], self.result['failure_question']), ('reference', 1))
        self.assertEqual(self.result['retry_requests'], 2)
        self.assertNotIn('paired_result', self.result)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_global_side_retry_ceiling_cannot_consume_extra_budget(self):
        self.result = {}
        self.outcome = lambda role, case, attempt, index: Completion('', complete=False, issue='stream_interrupted') if attempt == 1 else None
        with self.assertRaisesRegex(EndpointError, 'stream_interrupted'):
            self.run_paper()
        side, = self.result['exam']['sides']
        self.assertEqual((side['completed'], side['retry_requests'], self.result['failure_question']), (24, 24, 25))
        self.assertEqual(len(self.calls), 49)
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_user_cancellation_releases_hold_and_retains_last_answer(self):
        self.result = {}
        def outcome(role, case, attempt, call_number):
            if call_number == 3:
                self.monitor.cancel.set()
            return None
        self.outcome = outcome
        with self.assertRaises(Cancelled):
            self.run_paper()
        side, = self.result['exam']['sides']
        self.assertFalse(self.result['exam']['submitted'])
        self.assertEqual((side['completed'], self.result['failure_question']), (3, 3))
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_output_limit_is_not_a_completed_answer_or_a_retry(self):
        self.result = {}
        self.outcome = lambda role, case, attempt, index: Completion(
            '{"answer":42}', complete=False, issue='output_limit')
        with self.assertRaisesRegex(EndpointError, 'output_limit'):
            self.run_paper()
        side, = self.result['exam']['sides']
        self.assertFalse(self.result['exam']['submitted'])
        self.assertEqual((side['completed'], side['retry_requests'], len(self.calls)), (0, 0, 1))
        self.assertEqual(self.store.budget()['held_requests'], 0)

    def test_preflight_requires_enough_budget_for_the_retries(self):
        self.result = {}
        self.store.set_limits(143, 10_000_000)
        with self.assertRaises(BudgetExceeded):
            self.run_paper()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.result['exam']['submitted'])
        self.assertEqual(self.store.budget()['held_requests'], 0)


class Client:
    def __init__(self, owner, target):
        self.owner = owner
        self.role = target.role

    def complete(self, case):
        entry = self.role, case
        self.owner.calls.append(entry)
        if self.owner.outcome:
            response = self.owner.outcome(self.role, case, self.owner.calls.count(entry), len(self.owner.calls))
            if response is not None:
                return response
        return Completion(json.dumps({'answer': case.expected}))


if __name__ == '__main__':
    unittest.main()
