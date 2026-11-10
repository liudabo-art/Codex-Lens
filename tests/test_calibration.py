import importlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest.mock import patch
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from relay_auditor.transport import EndpointError,Target
from test_service import FakeClient

def outcome(plan,kind,index=0,*,complete=True,detected=False):
    return {'schema_version':2,'manifest_hash':plan['manifest_hash'],'suite_version':plan['suite_version'],
            'audit_index':plan['audit_index'],'applied_audit_index':plan['audit_index'] if complete else None,'cancelled':False,
            'phase':'validation','scenario':kind,'trial_index':index,'day':'2026-11-04','complete':complete,'detected':detected,
            'valid_pairs':40 if complete else 0,'attempted_pairs':40,'regressions':40 if detected else 0,'improvements':0,
            'p_value':(2**-40 if detected else 1.0) if complete else None,'requests':80,'response_count':80,'network_failures':0,'alternative_calls':0,
            'reported_tokens':2400,'unknown_usage':0,'estimated_tokens':500000}


def pilot_outcomes(plan):
    return [outcome(plan, scenario, index) | {'phase': 'pilot', 'day': '2026-11-03'}
            for scenario in plan['scenarios'] for index in range(plan['pilot_trials'])]


class CalibrationTests(unittest.TestCase):
    def test_cli_study_init_does_not_load_saved_relay_profiles(self):
        from relay_auditor import cli
        with tempfile.TemporaryDirectory() as folder, patch.object(cli,'data_directory',return_value=Path(folder)):
            output=io.StringIO()
            with patch.object(cli,'Auditor',side_effect=AssertionError('private profiles loaded')), \
                 redirect_stdout(output), redirect_stderr(io.StringIO()):
                status=cli.main(['calibration-init','--primary-model','gpt-primary','--alternative-model','gpt-alternative'])
            self.assertEqual(status,0)
            self.assertIn('"scope": "primary"',output.getvalue())

    def test_primary_study_runs_deployed_assessment_with_frozen_audit_index(self):
        from relay_auditor import assessment, calibration
        from relay_auditor.statistics import spending_alpha
        plan = calibration.freeze('gpt-primary', 'gpt-alternative', Protocol(), samples=10,
                                  scope='primary', audit_index=3)
        self.assertEqual(plan['scenarios'], ['healthy', 'substitution'])
        self.assertEqual(plan['planned_requests'], 4400)
        self.assertEqual(plan['suite_version'], assessment.VERSION)
        self.assertIn('assessment', plan['implementation_hashes'])
        self.assertEqual(plan['alpha'], spending_alpha(3))
        primary = Target('https://api.openai.com/v1', 'key', 'gpt-primary', Protocol(), role='reference')
        alternative = Target('https://api.openai.com/v1', 'key', 'gpt-alternative', Protocol(), role='reference')
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                with patch.object(assessment, 'run_assessment', wraps=assessment.run_assessment) as run:
                    row = calibration.collect_trial(plan, 'substitution', 0, 'pilot', primary, alternative, store,
                                                    client_factory=FakeClient, date='2026-11-03')
                run.assert_called_once()
                self.assertEqual(row['audit_index'], 3)
                self.assertIsNone(row['applied_audit_index'])
                self.assertEqual(row['alternative_calls'], 10)
                self.assertEqual(row['valid_pairs'], 10)
                self.assertEqual(row['requests'], 20)
                self.assertFalse(row['complete'])
                report = calibration.evaluate(plan,[row])
                pilot = report['scenarios']['substitution']
                self.assertEqual(pilot['sample_count'],0)
                self.assertEqual(pilot['pilot_trials'],1)
                self.assertEqual(pilot['pilot_usage']['requests'],20)
                self.assertEqual(sum(task['reference_correct'] for task in pilot['pilot_tasks']),10)
                self.assertEqual(sum(task['target_correct'] for task in pilot['pilot_tasks']),10)
                self.assertEqual(store.usage()['reference_requests'], 20)
                self.assertEqual(store.usage()['probe_requests'], 0)
                self.assertEqual(store.next_audit()[0], 1)
                self.assertEqual(store.history(), [])
                with self.assertRaisesRegex(ValueError, 'invalid_trial'):
                    calibration.collect_trial(plan, 'mixed_10', 0, 'pilot', primary, alternative, store,
                                              client_factory=FakeClient, date='2026-11-03')
            finally:
                store.close()

    def test_extended_context_control_uses_specialist_suite_and_clips_only_one_side(self):
        from relay_auditor import assessment,calibration
        plan=calibration.freeze('gpt-primary','gpt-alternative',Protocol(),samples=2,scope='extended')
        primary=Target('https://api.openai.com/v1','key','gpt-primary',Protocol(),role='reference')
        alternative=Target('https://api.openai.com/v1','key','gpt-alternative',Protocol(),role='reference')
        prompts=[]
        class Client(FakeClient):
            def complete(self,case):
                prompts.append((self.target.model,case.kind,len(case.prompt)))
                return super().complete(case)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:
                store.set_limits(100,200000)
                with patch.object(assessment,'run_assessment') as run:
                    row=calibration.collect_trial(plan,'context_truncated',0,'pilot',primary,alternative,store,
                                                  client_factory=Client,date='2026-11-03')
                run.assert_not_called()
                self.assertEqual(row['suite_version'],plan['specialist_context_suite'])
                self.assertEqual(row['requests'],4)
                self.assertEqual(row['valid_pairs'],2)
                self.assertEqual({(model,kind) for model,kind,_ in prompts},{('gpt-primary','context')})
                self.assertLess(prompts[0][2],prompts[1][2]/2)
                self.assertGreater(prompts[2][2],prompts[3][2]*2)
            finally:
                store.close()

    def test_calibration_official_authentication_failure_uses_production_stop_rule(self):
        from relay_auditor import calibration
        plan=calibration.freeze('gpt-primary','gpt-alternative',Protocol(),samples=10)
        primary=Target('https://api.openai.com/v1','key','gpt-primary',Protocol(),role='reference')
        alternative=Target('https://api.openai.com/v1','key','gpt-alternative',Protocol(),role='reference')
        class Client(FakeClient):
            def complete(self,case):
                if self.target.model=='gpt-primary':
                    raise EndpointError('authentication_failed')
                return super().complete(case)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:
                row=calibration.collect_trial(plan,'substitution',0,'pilot',primary,alternative,store,
                                              client_factory=Client,date='2026-11-03')
                self.assertEqual(row['requests'],11)
                self.assertEqual(row['unknown_usage'],1)
                self.assertEqual(row['valid_pairs'],0)
                self.assertFalse(row['complete'])
                self.assertFalse(row['detected'])
            finally:
                store.close()

    def test_freeze_hash_rejects_changes_and_ci_does_not_certify_tiny_samples(self):
        module=importlib.import_module('relay_auditor.calibration')
        plan=module.freeze('gpt-primary','gpt-alternative',Protocol(),samples=40,trials=100)
        module.validate(plan)
        with self.assertRaises(ValueError): module.validate(plan|{'samples':1})
        report=module.evaluate(plan,[outcome(plan,'healthy'),outcome(plan,'substitution',detected=True)])
        self.assertFalse(report['candidate_pass'])
        self.assertEqual(report['validation_state'],'experimental')

    def test_missing_outcomes_cannot_pass_by_abstaining(self):
        module=importlib.import_module('relay_auditor.calibration')
        plan=module.freeze('gpt-primary','gpt-alternative',Protocol())
        rows=[outcome(plan,kind,i,complete=False) for kind in ('healthy','substitution') for i in range(100)]
        report=module.evaluate(plan,rows)
        self.assertFalse(report['candidate_pass'])
        self.assertGreater(report['scenarios']['healthy']['interval'][1],.05)
        self.assertEqual(report['scenarios']['substitution']['interval'][0],0)

    def test_controlled_trial_budgets_every_call_and_requires_new_day_validation(self):
        module=importlib.import_module('relay_auditor.calibration')
        plan=module.freeze('gpt-primary','gpt-alternative',Protocol(),samples=2,trials=100)
        primary=Target('https://api.openai.com/v1','key','gpt-primary',Protocol(),role='reference')
        alternative=Target('https://api.openai.com/v1','key','gpt-alternative',Protocol(),role='reference')
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            row=module.collect_trial(plan,'healthy',0,'pilot',primary,alternative,store,client_factory=FakeClient,date='2026-11-03')
            self.assertEqual(store.budget()['requests'],4)
            self.assertEqual(row['valid_pairs'],2)
            with self.assertRaises(ValueError):
                module.collect_trial(plan,'healthy',0,'pilot',primary,alternative,store,records=[row],client_factory=FakeClient,date='2026-11-03')
            with self.assertRaises(ValueError):
                module.collect_trial(plan,'healthy',0,'validation',primary,alternative,store,records=[row],client_factory=FakeClient,date='2026-11-03')
            store.close()

    def test_duplicated_or_cross_study_outcomes_cannot_improve_power(self):
        from relay_auditor.calibration import freeze,evaluate
        plan=freeze('gpt-primary','gpt-alternative',Protocol())
        row=outcome(plan,'substitution',detected=True)
        with self.assertRaises(ValueError): evaluate(plan,[row,row])
        with self.assertRaises(ValueError): evaluate(plan,[row|{'manifest_hash':'0'*64}])

    def test_calibration_verdict_must_agree_with_recorded_pair_counts(self):
        from relay_auditor.calibration import freeze,evaluate
        plan=freeze('gpt-primary','gpt-alternative',Protocol())
        forged=outcome(plan,'substitution',detected=True) | {'regressions': 0}
        with self.assertRaisesRegex(ValueError, 'invalid_outcomes'):
            evaluate(plan,[forged])

    def test_review_candidate_requires_disjoint_cross_date_validation_blocks(self):
        from relay_auditor.calibration import freeze, evaluate
        plan = freeze('gpt-primary', 'gpt-alternative', Protocol(), seed=42)
        pilots = pilot_outcomes(plan)
        rows = [outcome(plan, scenario, i, detected=scenario == 'substitution')
                for scenario in plan['scenarios'] for i in range(plan['trials'])]
        self.assertFalse(evaluate(plan, pilots + rows)['candidate_pass'])
        for row in rows:
            index = row['trial_index']
            row['day'] = '2026-11-04' if index < 34 else '2026-11-06' if index < 67 else '2026-11-08'
        report = evaluate(plan, pilots + rows)
        self.assertTrue(report['candidate_pass'])
        self.assertEqual([row['sample_count'] for row in report['validation_blocks']], [68, 66, 66])

    def test_paid_collection_rejects_later_block_before_prior_block_finishes(self):
        from relay_auditor.calibration import freeze, collect_trial
        plan = freeze('gpt-primary', 'gpt-alternative', Protocol(), seed=42)
        primary = Target('https://api.openai.com/v1', 'synthetic', 'gpt-primary', Protocol(), role='reference')
        alternative = Target('https://api.openai.com/v1', 'synthetic', 'gpt-alternative', Protocol(), role='reference')
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                store.set_limits(100, 1000000)
                with self.assertRaisesRegex(ValueError, 'validation_block_not_ready'):
                    collect_trial(plan, 'healthy', 34, 'validation', primary, alternative, store,
                                  records=pilot_outcomes(plan), client_factory=FakeClient, date='2026-11-06')
                self.assertEqual(store.budget()['requests'], 0)
            finally:
                store.close()

    def test_keyboard_interrupt_preserves_unknown_trial_and_budget(self):
        from relay_auditor.calibration import freeze,collect_trial,evaluate
        plan=freeze('gpt-primary','gpt-alternative',Protocol(),samples=40)
        primary=Target('https://api.openai.com/v1','key','gpt-primary',Protocol(),role='reference')
        alternative=Target('https://api.openai.com/v1','key','gpt-alternative',Protocol(),role='reference')
        class Interrupted(FakeClient):
            def complete(self,case): raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:
                store.set_limits(1000,3000000)
                row=collect_trial(plan,'healthy',0,'pilot',primary,alternative,store,client_factory=Interrupted)
                self.assertTrue(row['cancelled']); self.assertFalse(row['complete'])
                self.assertEqual(row['unknown_usage'],1)
                self.assertEqual(store.budget()['requests'],1)
                self.assertFalse(evaluate(plan,[row])['candidate_pass'])
            finally: store.close()


if __name__=='__main__':unittest.main()
