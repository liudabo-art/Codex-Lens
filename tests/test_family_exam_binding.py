"""Version-bound confirmation; only synthetic in-memory clients."""
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch
from relay_auditor.core import Auditor
from relay_auditor.exam_registry import get_exam_spec
from relay_auditor.protocol import Protocol
from test_assessment import SimulatedClient

class FamilyExamBindingTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.auditor=Auditor(directory.name,client_factory=SimulatedClient); self.addCleanup(self.auditor.close)
        self.alias=self.auditor.configure('https://relay.invalid/v1','synthetic','deepseek-flash',Protocol(wire_api='deepseek'))
        self.auditor.store.set_limits(1000,10000000)

    def test_legacy_plan_identifies_the_selected_family_and_suite(self):
        plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
        self.assertEqual(plan.get('model_family'),'deepseek')
        self.assertEqual(plan.get('suite_version'),'exam-v2')

    def test_plan_binds_every_frozen_spec_field_to_an_immutable_identifier(self):
        spec=get_exam_spec('deepseek')
        plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
        identity=getattr(spec,'paper_spec_id',None)
        self.assertIsInstance(identity,str,'exam specifications need a public immutable binding')
        self.assertRegex(identity,r'^exam-spec-v1-[a-f0-9]{64}$')
        self.assertEqual(plan.get('paper_spec_id'),identity)
        for fields in ({'family':'gpt'},{'version':'future-exam-v9'},{'sizes':(120,)},
                       {'task_kinds':tuple(reversed(spec.task_kinds))},
                       {'max_prompt_bytes':spec.max_prompt_bytes+1},
                       {'max_retries_per_item':spec.max_retries_per_item+1}):
            with self.subTest(fields=fields):
                self.assertNotEqual(replace(spec,**fields).paper_spec_id,identity)
        self.assertEqual(replace(spec).paper_spec_id,identity)

    def test_task_kind_only_change_invalidates_confirmation_without_spend(self):
        spec=get_exam_spec('deepseek')
        plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
        changed=replace(spec,task_kinds=tuple(reversed(spec.task_kinds)))
        with patch('relay_auditor.planning.get_exam_spec',return_value=changed),patch.object(self.auditor.service,'_drain'):
            with self.assertRaisesRegex(ValueError,'exam_changed'):
                self.auditor.submit(self.alias,'capability_exam',120,exam_plan_id=plan['exam_plan_id'])
        self.assertFalse(self.auditor.service.pending)
        self.assertEqual(self.auditor.store.budget()['requests'],0)
        self.assertEqual(self.auditor.store.budget()['held_requests'],0)

    def test_changed_tasks_removed_size_and_revoked_family_invalidate_queued_exams(self):
        service=self.auditor.service
        spec=get_exam_spec('deepseek')
        for boundary in ('tasks','size','family'):
            with self.subTest(boundary=boundary):
                plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
                with patch.object(service,'_drain'):
                    job=self.auditor.submit(self.alias,'capability_exam',120,exam_plan_id=plan['exam_plan_id'])
                self.assertEqual(service.jobs[job]['state'],'queued')
                if boundary=='family':
                    drift=patch('relay_auditor.planning.get_exam_spec',side_effect=ValueError('invalid_exam_paper'))
                else:
                    changed=replace(spec,**({'task_kinds':tuple(reversed(spec.task_kinds))}
                                             if boundary=='tasks' else {'sizes':(180,)}))
                    drift=patch('relay_auditor.planning.get_exam_spec',return_value=changed)
                try:
                    with drift,patch('relay_auditor.controller.threading.Thread'):
                        try:
                            service._drain()
                        except ValueError as error:
                            self.fail(f'queued specification drift must become exam_changed, got {error}')
                    self.assertEqual(service.jobs[job]['state'],'exam_changed')
                    self.assertFalse(service.pending)
                    self.assertFalse(service.busy)
                    budget=self.auditor.store.budget()
                    self.assertEqual((budget['requests'],budget['estimated_tokens'],budget['held_requests'],budget['held_tokens']),
                                     (0,0,0,0))
                finally:
                    # A regressed queue may mark a mocked worker running. Clean up
                    # that test-only state so failures still close the real store.
                    if service.current_job==job:
                        service.current_job=None
                        service.busy=False
                    service.jobs.pop(job,None)

    def test_removed_size_or_family_invalidates_confirmation_without_spend(self):
        spec=get_exam_spec('deepseek')
        for removed in ('size','family'):
            with self.subTest(removed=removed):
                plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
                drift=(patch('relay_auditor.planning.get_exam_spec',return_value=replace(spec,sizes=(180,)))
                       if removed=='size' else
                       patch('relay_auditor.planning.get_exam_spec',side_effect=ValueError('invalid_exam_paper')))
                with drift,patch.object(self.auditor.service,'_drain'):
                    with self.assertRaisesRegex(ValueError,'exam_changed'):
                        self.auditor.submit(self.alias,'capability_exam',120,exam_plan_id=plan['exam_plan_id'])
                self.assertFalse(self.auditor.service.pending)
                self.assertEqual(self.auditor.store.budget()['requests'],0)
                self.assertEqual(self.auditor.store.budget()['held_requests'],0)

    def test_changed_suite_invalidates_confirmation_before_queue_or_spend(self):
        from relay_auditor.controller import exam_plan as original
        plan=self.auditor.estimate(self.alias,'capability_exam',120,comparison='relay_only')
        def changed(*args,**kwargs):
            current=original(*args,**kwargs); current['suite_version']='other-suite'; return current
        with patch('relay_auditor.controller.exam_plan',side_effect=changed),patch.object(self.auditor.service,'_drain'):
            with self.assertRaisesRegex(ValueError,'exam_changed'):
                self.auditor.submit(self.alias,'capability_exam',120,exam_plan_id=plan['exam_plan_id'])
        self.assertEqual(self.auditor.store.budget()['requests'],0)
        self.assertEqual(self.auditor.service.pending,[])

    def test_unsupported_effort_is_rejected_without_budget_or_queue(self):
        alias=self.auditor.configure('https://relay.invalid/v1','synthetic','claude-sonnet-4-5',
                                    Protocol(wire_api='anthropic',reasoning_effort='high'))
        plan=self.auditor.estimate(alias,'capability_exam',120,comparison='relay_only')
        self.assertEqual(plan['status'],'unsupported_parameters')
        for mode in ('assessment','quality'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'unsupported_parameters'):
                self.auditor.submit(alias,mode)
        self.assertEqual(self.auditor.store.budget()['requests'],0)
        self.assertFalse(self.auditor.service.pending)
