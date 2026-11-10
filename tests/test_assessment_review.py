import tempfile
import unittest
from unittest.mock import patch

from relay_auditor.controller import Service
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from test_assessment import SimulatedClient


class AssessmentReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.store.set_limits(100, 500000)
        self.addCleanup(self.store.close)
        self.service = Service(self.store, client_factory=SimulatedClient)
        self.addCleanup(self.service.stop)
        self.alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'deepseek-flash',
                                            Protocol(wire_api='deepseek'), reference_key='synthetic-official')

    def run_assessment(self, **options):
        # Exercise submission and persistence without timing the background worker.
        with patch('relay_auditor.controller.threading') as scheduler:
            job = self.service.submit(self.alias, 'assessment', **options)
        scheduler.Thread.return_value.start.assert_called_once_with()
        worker = scheduler.Thread.call_args.kwargs
        worker['target'](*worker['args'])
        self.assertEqual(self.service.jobs[job]['state'], 'finished')
        return job, self.service.monitors[self.alias].last_result

    def test_review_requires_explicit_request_and_keeps_screen_provenance(self):
        preview = self.service.estimate(self.alias, 'assessment')
        self.assertEqual((preview['target_requests'], preview['reference_requests']), (10, 10))
        self.assertEqual(self.store.budget()['requests'], 0)
        screen_job, screen = self.run_assessment(seed=42)
        self.assertEqual(screen['paired_result']['valid_pairs'], 10)
        self.assertEqual(screen['reference_comparison_conditions']['wire_api'], 'deepseek')
        self.assertEqual(self.store.budget()['requests'], 20)
        self.assertTrue(self.service.snapshot()['targets'][0]['review_available'])
        preview = self.service.estimate(self.alias, 'assessment', 40)
        self.assertEqual((preview['target_requests'], preview['reference_requests']), (40, 40))
        with patch('relay_auditor.controller.secrets.randbelow', return_value=0):
            _, review = self.run_assessment(samples=40, expected_requests=preview['required_requests'], review_of=screen_job)
        self.assertEqual(review['review_of'], screen_job)
        self.assertGreaterEqual(review['task_seed'], screen['task_seed'] + screen['task_count'])
        self.assertEqual(self.store.budget()['requests'], 100)
        self.assertEqual(self.store.usage()['probe_requests'], 50)
        self.assertEqual(self.store.usage()['reference_requests'], 50)
        self.assertFalse(self.service.snapshot()['targets'][0]['review_available'])
        self.assertEqual(self.store.history()[0]['review_of'], screen_job)

    def test_review_fails_closed_after_changed_screen_or_budget(self):
        screen_job, _ = self.run_assessment(seed=42)
        with self.assertRaisesRegex(ValueError, 'assessment_changed'):
            self.service.submit(self.alias, 'assessment', 40, review_of=screen_job, expected_requests=40)
        with self.assertRaisesRegex(ValueError, 'assessment_changed'):
            self.service.submit(self.alias, 'assessment', 10, review_of=screen_job, expected_requests=20)
        self.service.update_target(self.alias, display_name='Synthetic', model='deepseek-flash', reasoning_effort='high')
        with self.assertRaisesRegex(ValueError, 'assessment_changed'):
            self.service.submit(self.alias, 'assessment', 40, review_of=screen_job, expected_requests=80)
        self.assertEqual(self.store.budget()['requests'], 20)

    def test_review_requires_new_screen_after_target_key_change(self):
        screen_job, _ = self.run_assessment(seed=42)
        self.service.credentials(self.alias, 'another-synthetic-key')
        self.assertFalse(self.service.snapshot()['targets'][0]['review_available'])
        with self.assertRaisesRegex(ValueError, 'assessment_changed'):
            self.service.submit(self.alias, 'assessment', 40, review_of=screen_job, expected_requests=80)
        self.assertEqual(self.store.history()[0]['job_id'], screen_job)
