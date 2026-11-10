import tempfile
import threading
import time
import unittest
from pathlib import Path

from relay_auditor.controller import Service
from relay_auditor.storage import Store
from test_service import FakeClient


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'data'); self.addCleanup(self.store.close)
        FakeClient.calls=[]; FakeClient.interrupt=None
        self.service=Service(self.store,client_factory=FakeClient)
        self.addCleanup(self.service.stop)
        self.alias=self.service.configure('https://relay.example/v1','key','gpt-test')

    def wait_idle(self):
        deadline=time.monotonic()+4
        while self.service.busy and time.monotonic()<deadline: time.sleep(0.01)
        self.assertFalse(self.service.busy)

    def test_quality_is_shared_deterministic_workflow_with_four_dimensions(self):
        result=self.service.run(self.alias,'quality',samples=5)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['capability_correct'],5)
        self.assertEqual(result['suite_version'],'quality-v2')
        self.assertEqual(set(result['dimensions']),{'quality','behavior','reliability','stability'})
        self.assertEqual(result['evidence_level'],'basic_observation')
        self.assertEqual(self.store.budget()['requests'],5)

    def test_queue_cancellation_does_not_send_queued_work(self):
        entered=threading.Event(); release=threading.Event()
        class Blocking(FakeClient):
            def complete(inner,case):
                entered.set(); release.wait(2)
                return super().complete(case)
        self.service.client_factory=Blocking
        first=self.service.submit(self.alias,'screen')
        self.assertTrue(entered.wait(2))
        second=self.service.submit(self.alias,'quality',samples=5)
        self.service.cancel(second)
        release.set(); self.wait_idle()
        self.assertEqual(self.store.budget()['requests'],3)
        jobs={j['job_id']:j for j in self.service.snapshot()['jobs']}
        self.assertEqual(jobs[second]['state'],'cancelled')
        self.assertEqual(jobs[first]['state'],'finished')

    def test_reasoning_compares_two_settings_without_asserting_high_must_win(self):
        result=self.service.run(self.alias,'reasoning',samples=2)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['reasoning_comparison']),2)
        self.assertEqual(result['identity_state'],'no_reference')
        self.assertFalse(result.get('detected_anomaly',False))
        self.assertEqual(self.store.budget()['requests'],4)

    def test_replay_seed_and_task_count_are_public_without_raw_answers(self):
        result=self.service.run(self.alias,'quality',samples=5,seed=42)
        self.assertEqual(result['task_seed'],42)
        self.assertEqual(result['task_count'],5)
        self.assertNotIn('prompt',result)
        self.assertNotIn('answer',result)
        with self.assertRaises(ValueError): self.service.run(self.alias,'quality',seed=-1)


if __name__=='__main__':unittest.main()
