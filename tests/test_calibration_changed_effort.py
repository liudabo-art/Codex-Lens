"""A controlled effort change must be executable before a study is frozen."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from relay_auditor import calibration, cli
from relay_auditor.protocol import Protocol


class ChangedEffortStudyTests(unittest.TestCase):
    def test_unsupported_changed_effort_cannot_freeze_an_extended_study(self):
        cases=(
            ('gpt-6.1-sol','gpt-6-luna',Protocol(reasoning_effort='low')),
            ('gpt-4.1','gpt-4o',Protocol()),
            ('gpt-5.6-sol','gpt-5.6-terra',Protocol(reasoning_effort='none',temperature=.5)),
        )
        for primary,alternative,protocol in cases:
            with self.subTest(primary=primary), \
                 patch('relay_auditor.calibration.Service', side_effect=AssertionError('service_created')), \
                 patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('api_client_created')), \
                 patch('socket.socket', side_effect=AssertionError('network_opened')):
                with self.assertRaisesRegex(ValueError,'^unsupported_study_reasoning$'):
                    calibration.freeze(primary,alternative,protocol,scope='extended',seed=42)

    def test_primary_scope_never_requires_an_unused_changed_effort(self):
        for primary,alternative,protocol in (
            ('gpt-6.1-sol','gpt-6-luna',Protocol(reasoning_effort='low')),
            ('gpt-4.1','gpt-4o',Protocol()),
            ('gpt-5.6-sol','gpt-5.6-terra',Protocol(reasoning_effort='none',temperature=.5)),
        ):
            with self.subTest(primary=primary):
                plan=calibration.freeze(primary,alternative,protocol,scope='primary',seed=42)
                self.assertNotIn('reasoning_changed',plan['scenarios'])
                self.assertEqual(plan['protocol']['reasoning_effort'],protocol.reasoning_effort)
                calibration.validate(plan)

    def test_documented_deepseek_alias_does_not_create_a_fake_changed_control(self):
        protocol=Protocol(wire_api='deepseek',reasoning_effort='minimal')
        with self.assertRaisesRegex(ValueError,'^unsupported_study_reasoning$'):
            calibration.freeze('deepseek-v4-pro','deepseek-flash',protocol,
                               family='deepseek',scope='extended',seed=42)
        primary=calibration.freeze('deepseek-v4-pro','deepseek-flash',protocol,
                                   family='deepseek',scope='primary',seed=42)
        self.assertEqual(primary['protocol']['reasoning_effort'],'minimal')
        self.assertNotIn('reasoning_changed',primary['scenarios'])

    def test_reviewed_gpt_and_deepseek_extended_controls_preserve_exact_settings(self):
        for family,primary,alternative,wire in (
            ('gpt','gpt-5.6-sol','gpt-5.6-terra','responses'),
            ('deepseek','deepseek-v4-pro','deepseek-flash','deepseek'),
        ):
            for suite in (None,'assessment-v4','exam-v2'):
                with self.subTest(family=family,suite=suite):
                    protocol=Protocol(wire_api=wire,reasoning_effort='high')
                    plan=calibration.freeze(primary,alternative,protocol,scope='extended',seed=42,
                                            family=family,suite=suite,samples=120)
                    self.assertIn('reasoning_changed',plan['scenarios'])
                    self.assertEqual(plan['changed_reasoning_effort'],'low')
                    self.assertEqual(plan['protocol']['reasoning_effort'],'high')
                    calibration.validate(plan)

    def test_offline_cli_rejects_an_unexecutable_control_without_private_state(self):
        out,err=StringIO(),StringIO()
        with patch.object(cli,'data_directory',side_effect=AssertionError('private_directory_read')), \
             patch.object(cli,'Store',side_effect=AssertionError('budget_store_opened')), \
             patch.object(cli,'Auditor',side_effect=AssertionError('profiles_read')), \
             patch('relay_auditor.calibration_cli.hidden',side_effect=AssertionError('credential_prompt')), \
             patch('relay_auditor.transport.APIClient.__init__',side_effect=AssertionError('api_client_created')), \
             patch('socket.socket',side_effect=AssertionError('network_opened')), \
             redirect_stdout(out),redirect_stderr(err):
            status=cli.main(['calibration-plan','--primary-model','gpt-6.1-sol',
                             '--alternative-model','gpt-6-luna','--reasoning-effort','low',
                             '--study-scope','extended','--seed','42'])
        self.assertEqual(status,2)
        self.assertEqual(out.getvalue(),'')
        self.assertEqual(err.getvalue().strip(),'invalid_arguments_or_configuration')
