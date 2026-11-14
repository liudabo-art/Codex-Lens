"""New research evidence traverses production collection and offline CLI reports."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relay_auditor import calibration, calibration_cli
from relay_auditor.official import restore_reference
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from relay_auditor.transport import Completion, EndpointError

MODELS=(('gpt','exam-v2','responses','gpt-6.1-sol','gpt-6-luna'),
        ('claude','claude-exam-v1','anthropic','claude-opus-4-6','claude-sonnet-4-6'),
        ('deepseek','exam-v2','deepseek','deepseek-v4-pro','deepseek-flash'),
        ('gemini','gemini-exam-v1','gemini','gemini-3.1-pro-preview','gemini-3-flash-preview'))

class CalibrationMetricsIntegrationTests(unittest.TestCase):
    def collect(self, selected, *, failure=None, limits=(1000,20_000_000)):
        family,suite,wire,primary_id,alternative_id=selected
        manifest=calibration.freeze(primary_id,alternative_id,Protocol(wire_api=wire),
                                    family=family,suite=suite,samples=120,seed=42)
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        store=Store(directory.name); self.addCleanup(store.close); store.set_limits(*limits)
        protocol=Protocol(**manifest['protocol']); calls=[]
        primary=restore_reference(manifest['official_preset'],'synthetic',primary_id,protocol)
        alternative=restore_reference(manifest['official_preset'],'synthetic',alternative_id,protocol)
        class Client:
            def __init__(self,target): self.target=target
            def complete(self,case):
                calls.append(self.target.model)
                if failure and self.target.model==primary_id: raise EndpointError(failure)
                if not failure and self.target.model==alternative_id and case.seed==10_000_042:
                    return Completion('synthetic malformed completed reply')
                return Completion(json.dumps({'answer':case.expected}),
                                  {'input_tokens':10,'output_tokens':5,'total_tokens':15})
        with patch('relay_auditor.controller.Service.wait_for_retry',return_value=None):
            row=calibration.collect_trial(manifest,'substitution',0,'pilot',primary,alternative,store,
                                          client_factory=Client,date='2026-11-14')
        calibration.checked_records(manifest,[row])
        return manifest,row,store,calls

    def report_via_cli(self, manifest, row, store):
        study_id=manifest['manifest_hash'][:32]; root=Path(store.directory)/'studies'/study_id
        root.mkdir(parents=True)
        (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        (root/'outcomes.json').write_text(json.dumps([row]),encoding='utf-8')
        with patch('relay_auditor.calibration_cli.hidden',side_effect=AssertionError('unexpected credential access')), \
             patch('relay_auditor.calibration.APIClient',side_effect=AssertionError('unexpected model request')):
            return calibration_cli.command(SimpleNamespace(command='calibration-report',study_id=study_id),store)

    def test_four_family_formal_score_counts_survive_offline_cli_report(self):
        for selected in MODELS:
            with self.subTest(family=selected[0]):
                manifest,row,store,calls=self.collect(selected)
                self.assertTrue(row['complete'])
                counts=row['exam_score_counts']
                self.assertEqual(counts['reference']['correct'],120)
                self.assertEqual(counts['relay']['correct'],119)
                self.assertEqual(counts['relay']['format_failures'],1)
                self.assertEqual(len(calls),240)
                # Anonymous aggregate fixture for a completed formal trial. Formal
                # outcomes intentionally carry no pilot-only item arrays.
                formal={key:value for key,value in row.items() if key not in ('pilot_items','pilot_tasks')}
                formal.update(phase='validation',day='2026-11-15')
                report=self.report_via_cli(manifest,formal,store)
                stage=report['scenarios']['substitution']['quality_metrics']['validation']
                self.assertEqual(stage['complete_trials'],1)
                self.assertEqual(stage['completion_rate'],1)
                self.assertEqual(stage['inconclusive_rate'],0)
                self.assertAlmostEqual(stage['repeat_scores']['relay']['mean'],100*119/120)
                self.assertIsNone(stage['repeat_scores']['relay']['sample_stddev'])
                self.assertFalse(report['candidate_pass'])
                self.assertEqual(store.budget()['held_requests'],0)

    def test_four_family_failures_keep_side_question_and_do_not_become_scores(self):
        for selected in MODELS:
            with self.subTest(family=selected[0]):
                manifest,row,store,calls=self.collect(selected,failure='authentication_failed')
                self.assertFalse(row['complete'])
                self.assertEqual(row['trial_failure'],{'error_code':'authentication_failed',
                                                      'source_kind':'reference','question_number':1})
                stage=calibration.evaluate(manifest,[row])['scenarios']['substitution']['quality_metrics']['pilot']
                self.assertEqual(stage['completion_rate'],0)
                self.assertEqual(stage['inconclusive_rate'],1)
                self.assertEqual(stage['repeat_scores']['relay']['count'],0)
                self.assertEqual(stage['usage']['requests'],2)
                self.assertEqual(store.budget()['held_requests'],0)

    def test_prestart_budget_preserves_zero_progress_without_client_calls(self):
        manifest,row,store,calls=self.collect(MODELS[0],limits=(1,1))
        self.assertEqual(row['trial_failure']['error_code'],'budget_exhausted')
        self.assertFalse(calls)
        self.assertTrue(all(side['attempted']==0 for side in row['exam_score_counts'].values()))
        self.assertFalse(row['complete'])
        self.assertEqual(store.budget()['held_requests'],0)

    def test_private_error_text_never_enters_research_evidence(self):
        manifest,row,store,calls=self.collect(MODELS[1],failure='PRIVATE-SYNTHETIC-ERROR')
        self.assertEqual(row['trial_failure']['error_code'],'remote_error')
        report=calibration.evaluate(manifest,[row])
        self.assertNotIn('PRIVATE-SYNTHETIC',json.dumps([row,report]))

    def test_legacy_formal_record_has_unavailable_absolute_scores(self):
        manifest,row,store,calls=self.collect(MODELS[0])
        legacy={key:value for key,value in row.items() if key not in ('exam_score_counts','trial_failure','pilot_items','pilot_tasks')}
        legacy.update(phase='validation',day='2026-11-15')
        stage=calibration.evaluate(manifest,[legacy])['scenarios']['substitution']['quality_metrics']['validation']
        self.assertEqual(stage['score_evidence']['state'],'unavailable')
        self.assertEqual(stage['repeat_scores']['relay']['count'],0)
        self.assertIsNone(stage['repeat_scores']['relay']['mean'])
