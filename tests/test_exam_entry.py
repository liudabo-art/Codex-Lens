from contextlib import redirect_stderr
from io import StringIO
import tempfile
import unittest
from unittest.mock import patch

from relay_auditor.cli import main
from relay_auditor.core import Auditor
from relay_auditor.protocol import Protocol
from test_assessment import SimulatedClient


class ExamEntryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.auditor = Auditor(directory.name, client_factory=SimulatedClient)
        self.addCleanup(self.auditor.close)
        self.service = self.auditor.service
        self.alias = self.auditor.configure('https://relay.invalid/v1', 'synthetic', 'deepseek-flash',
                                            Protocol(wire_api='deepseek'), reference_key='synthetic-official')

    def test_previews_full_retry_budget_for_each_paper_and_side(self):
        for n in (120, 180):
            for comparison, factor in (('relay_only', 1), ('paired', 2)):
                with self.subTest(n=n, comparison=comparison):
                    plan = self.auditor.estimate(self.alias, 'capability_exam', n, comparison=comparison)
                    self.assertEqual(plan['required_requests'], factor * n)
                    self.assertEqual(plan['max_requests'], factor * n * 6 // 5)
                    self.assertEqual(plan['minimum_request_limit'], plan['max_requests'])
                    self.assertEqual(plan['status'], 'budget_exhausted')
                    self.assertNotIn('exam_plan_id', plan)
        self.assertEqual(self.auditor.store.budget()['requests'], 0)

    def test_cli_requires_side_selection_before_a_confirmed_exam(self):
        output = StringIO()
        with patch('relay_auditor.cli.Auditor', side_effect=AssertionError('opened local state')) as owner, redirect_stderr(output):
            self.assertEqual(main(['capability-exam', '--confirm-exam']), 2)
        owner.assert_not_called()
        self.assertIn('--comparison', output.getvalue())

    def test_rejects_unapproved_automatic_or_stale_exam(self):
        self.auditor.store.set_limits(500, 5_000_000)
        plan = self.auditor.estimate(self.alias, 'capability_exam', 120, comparison='paired')
        token = plan['exam_plan_id']
        with self.assertRaisesRegex(ValueError, 'exam_changed'):
            self.auditor.run(self.alias, 'capability_exam', 120)
        with self.assertRaisesRegex(ValueError, 'exam_changed'):
            self.auditor.submit(self.alias, 'capability_exam', 120, automatic=True, exam_plan_id=token)
        self.service.credentials(self.alias, 'rotated-synthetic-key')
        with self.assertRaisesRegex(ValueError, 'exam_changed'):
            self.auditor.submit(self.alias, 'capability_exam', 120, exam_plan_id=token)
        self.assertEqual(self.auditor.store.budget()['requests'], 0)

    def test_rechecks_queued_exam_after_target_settings_change(self):
        self.auditor.store.set_limits(500, 5_000_000)
        plan = self.auditor.estimate(self.alias, 'capability_exam', 120, comparison='relay_only')
        with patch.object(self.service, '_drain'):
            job = self.auditor.submit(self.alias, 'capability_exam', 120, exam_plan_id=plan['exam_plan_id'])
        self.service.update_target(self.alias, display_name='Synthetic', model='deepseek-flash', reasoning_effort='high')
        self.service._drain()
        self.assertEqual(self.service.jobs[job]['state'], 'exam_changed')
        self.assertEqual(self.auditor.store.budget()['requests'], 0)

    def test_one_confirmation_runs_once_with_explicit_relay_only(self):
        self.auditor.store.set_limits(500, 5_000_000)
        plan = self.auditor.estimate(self.alias, 'capability_exam', comparison='relay_only')
        result = self.auditor.run(self.alias, 'capability_exam', exam_plan_id=plan['exam_plan_id'])
        self.assertTrue(result['exam']['submitted'])
        self.assertEqual(result['task_count'], 120)
        self.assertIsNone(result['reference_model'])
        self.assertEqual(self.auditor.store.budget()['requests'], 120)
        self.assertEqual(self.auditor.store.budget()['held_requests'], 0)
        with self.assertRaisesRegex(ValueError, 'exam_changed'):
            self.auditor.run(self.alias, 'capability_exam', exam_plan_id=plan['exam_plan_id'])

    def test_output_limit_change_requires_a_fresh_exam_preview(self):
        self.auditor.store.set_limits(500, 10_000_000)
        plan = self.auditor.estimate(self.alias, 'capability_exam', comparison='paired')
        self.assertEqual(plan['max_output_tokens'], 2048)
        self.assertEqual(plan['reference_max_output_tokens'], 2048)
        self.service.update_target(self.alias, display_name='Synthetic', model='deepseek-flash', max_output_tokens=8192)
        with self.assertRaisesRegex(ValueError, 'exam_changed'):
            self.auditor.submit(self.alias, 'capability_exam', exam_plan_id=plan['exam_plan_id'])
        updated = self.auditor.estimate(self.alias, 'capability_exam', comparison='paired')
        self.assertEqual(updated['max_output_tokens'], 8192)
        self.assertEqual(updated['reference_max_output_tokens'], 8192)
        self.assertGreater(updated['estimated_tokens'], plan['estimated_tokens'])
        self.assertEqual(self.auditor.store.budget()['requests'], 0)

    def test_exam_preserves_existing_routine_review_candidate(self):
        self.auditor.store.set_limits(500, 5_000_000)
        with patch('relay_auditor.controller.threading') as scheduler:
            screen_job = self.auditor.submit(self.alias, 'assessment', seed=42)
        worker = scheduler.Thread.call_args.kwargs
        worker['target'](*worker['args'])
        self.assertEqual(self.auditor.snapshot()['targets'][0]['review_job_id'], screen_job)
        plan = self.auditor.estimate(self.alias, 'capability_exam')
        result = self.auditor.run(self.alias, 'capability_exam', exam_plan_id=plan['exam_plan_id'])
        self.assertTrue(result['exam']['submitted'])
        target = self.auditor.snapshot()['targets'][0]
        self.assertEqual(target['last_result']['mode'], 'capability_exam')
        self.assertEqual(target['review_job_id'], screen_job)
