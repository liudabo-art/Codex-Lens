"""Desktop/SDK service matrix using in-memory synthetic completions, never APIs."""
import json
import tempfile
import unittest
from unittest.mock import patch

from relay_auditor.core import Auditor
from relay_auditor.exporting import html_report
from relay_auditor.protocol import Protocol
from relay_auditor.reports import explain
from relay_auditor.transport import Completion, EndpointError

FAMILIES = (
    ('gpt-6.1-sol','responses','exam-v2'),
    ('claude-sonnet-4-6','anthropic','claude-exam-v1'),
    ('deepseek-flash','deepseek','exam-v2'),
    ('gemini-2.5-flash','gemini','gemini-exam-v1'),
)

class FourFamilyServiceTests(unittest.TestCase):
    def build(self, model, wire, *, paired=False, behavior=None):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        calls=[]
        class Synthetic:
            def __init__(self,target): self.target=target
            def complete(self,case):
                calls.append((self.target.role,case.seed))
                if behavior:
                    outcome=behavior(self.target,case,calls)
                    if outcome is not None: return outcome
                return Completion(json.dumps({'answer':case.expected}),
                                  {'input_tokens':10,'output_tokens':5,'total_tokens':15})
        auditor=Auditor(directory.name,client_factory=Synthetic); self.addCleanup(auditor.close)
        auditor.service.wait_for_retry=lambda *_:None
        alias=auditor.configure('https://synthetic.invalid/v1','synthetic',model,Protocol(wire_api=wire),
                                reference_key='synthetic-reference' if paired else None)
        auditor.store.set_limits(2000,30_000_000)
        return auditor,alias,calls

    def test_all_families_papers_sides_usage_and_shared_reports(self):
        for model,wire,version in FAMILIES:
            for samples in (120,180):
                for paired in (False,True):
                    with self.subTest(model=model,samples=samples,paired=paired):
                        auditor,alias,calls=self.build(model,wire,paired=paired)
                        plan=auditor.estimate(alias,'capability_exam',samples,comparison='paired' if paired else 'relay_only')
                        self.assertEqual(plan['status'],'ok')
                        self.assertEqual(plan['suite_version'],version)
                        result=auditor.run(alias,'capability_exam',exam_plan_id=plan['exam_plan_id'])
                        self.assertTrue(result['exam']['submitted'])
                        self.assertEqual(result['suite_version'],version)
                        self.assertEqual(len(calls),plan['required_requests'])
                        self.assertEqual(auditor.store.usage()['probe_requests'],samples)
                        self.assertEqual(auditor.store.usage()['reference_requests'],samples if paired else 0)
                        self.assertEqual(auditor.store.budget()['held_requests'],0)
                        snapshot=auditor.snapshot(); saved=snapshot['history'][0]
                        self.assertEqual(explain(result),explain(saved))
                        self.assertIn(explain(result)['headline'],html_report(snapshot))
                        self.assertEqual(len(saved['item_results']),samples*(2 if paired else 1))

    def test_failed_side_retry_and_terminal_failure_never_create_final_grade(self):
        for model,wire,version in FAMILIES:
            with self.subTest(model=model):
                def fail(target,case,calls):
                    if target.role=='reference': raise EndpointError('network_error')
                auditor,alias,calls=self.build(model,wire,paired=True,behavior=fail)
                plan=auditor.estimate(alias,'capability_exam',120)
                result=auditor.run(alias,'capability_exam',exam_plan_id=plan['exam_plan_id'])
                self.assertFalse(result['exam']['submitted'])
                self.assertEqual(len([x for x in calls if x[0]=='relay']),1)
                self.assertEqual(len([x for x in calls if x[0]=='reference']),3)
                self.assertEqual(auditor.store.budget()['held_requests'],0)
                self.assertFalse(explain(result)['score_tiles'])

    def test_budget_and_cancel_preserve_four_family_unsubmitted_state(self):
        for model,wire,version in FAMILIES:
            with self.subTest(model=model):
                auditor,alias,calls=self.build(model,wire)
                auditor.store.set_limits(100,100_000)
                plan=auditor.estimate(alias,'capability_exam',120)
                self.assertEqual(plan['status'],'budget_exhausted')
                self.assertNotIn('exam_plan_id',plan)
                self.assertFalse(calls)
                auditor.store.set_limits(2000,30_000_000)
                plan=auditor.estimate(alias,'capability_exam',120)
                original=auditor.service.client_factory
                class Cancel:
                    def __init__(self,target): self.target=target
                    def complete(self,case):
                        auditor.service.monitors[alias].cancel.set()
                        return original(self.target).complete(case)
                auditor.service.client_factory=Cancel
                result=auditor.run(alias,'capability_exam',exam_plan_id=plan['exam_plan_id'])
                self.assertEqual(result['status'],'cancelled')
                self.assertFalse(result['exam']['submitted'])
                self.assertEqual(auditor.store.budget()['held_requests'],0)

    def test_transient_stream_retry_keeps_one_format_loss_in_each_complete_paper(self):
        for model,wire,version in FAMILIES:
            with self.subTest(model=model):
                first=[]
                def recover(target,case,calls):
                    if not first: first.append(case.seed)
                    if case.seed==first[0]:
                        if calls.count((target.role,case.seed))==1:
                            return Completion('',complete=False,issue='stream_interrupted')
                        return Completion('synthetic malformed answer')
                auditor,alias,calls=self.build(model,wire,behavior=recover)
                plan=auditor.estimate(alias,'capability_exam',120)
                result=auditor.run(alias,'capability_exam',exam_plan_id=plan['exam_plan_id'])
                self.assertTrue(result['exam']['submitted'])
                self.assertEqual(result['capability_correct'],119)
                self.assertEqual(result['retry_requests'],1)
                items=result['item_results']
                self.assertEqual(len(items),120)
                failed=[item for item in items if item['format_state']=='answer_format']
                self.assertEqual(len(failed),1)
                self.assertEqual(failed[0]['attempts'],2)
                self.assertIsNone(failed[0]['correct'])
                self.assertEqual(len(calls),121)
                self.assertEqual(auditor.store.budget()['held_requests'],0)

    def test_all_families_reject_unreviewed_explicit_effort_before_spend(self):
        for model,wire in (('gpt-unreviewed','responses'),('claude-unreviewed','anthropic'),
                           ('deepseek-unreviewed','deepseek'),('gemini-unreviewed','gemini')):
            with self.subTest(model=model):
                auditor,alias,calls=self.build(model,wire)
                auditor.service.update_target(alias,display_name='Synthetic',model=model,reasoning_effort='high')
                plan=auditor.estimate(alias,'capability_exam',120)
                self.assertEqual(plan['status'],'unsupported_parameters')
                with self.assertRaisesRegex(ValueError,'unsupported_parameters'):
                    auditor.submit(alias,'assessment')
                self.assertFalse(calls)
                self.assertEqual(auditor.store.budget()['requests'],0)
