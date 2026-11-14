"""Offline study preparation uses public synthetic inputs, never account state."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from relay_auditor import cli, calibration
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store
from relay_auditor.transport import Completion

GPT_PRIMARY = 'gpt-5.6-sol'
GPT_ALTERNATIVE = 'gpt-5.6-terra'


class CalibrationReadinessTests(unittest.TestCase):
    def offline_plan(self, *options):
        output = io.StringIO()
        with patch.object(cli, 'data_directory', side_effect=AssertionError('private_directory_read')), \
             patch.object(cli, 'Store', side_effect=AssertionError('budget_store_opened')), \
             patch.object(cli, 'Auditor', side_effect=AssertionError('private_profiles_read')), \
             patch('relay_auditor.calibration_cli.hidden', side_effect=AssertionError('credential_prompt')), \
             patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('api_client_constructed')), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = cli.main(['calibration-plan', '--primary-model', GPT_PRIMARY,
                               '--alternative-model', GPT_ALTERNATIVE, '--seed', '42', *options])
        self.assertEqual(status, 0)
        return json.loads(output.getvalue())

    def test_plan_bypasses_private_state_and_marks_unverified_inputs(self):
        report = self.offline_plan('--suite', 'exam-v2', '--family', 'gpt')
        self.assertEqual(report['action'], 'offline_calibration_plan')
        self.assertEqual(report['real_api_requests'], 0)
        self.assertFalse(report['frozen'])
        self.assertFalse(report['collection_authorized'])
        self.assertNotIn('study_id', report)
        self.assertNotIn('manifest_hash', report)
        self.assertEqual(report['access_state'], 'not_checked')
        self.assertEqual(report['model_visibility'], 'not_checked')
        self.assertEqual(report['model_version_state'], 'requested_ids_unverified')
        self.assertEqual(report['validation_state'], 'experimental')
        self.assertEqual(report['budget']['state'], 'unknown')
        self.assertFalse(report['budget']['existing_daily_usage_checked'])
        self.assertIsNone(report['estimated_cost'])

    def test_exam_plan_stage_counts_reserve_retries_and_output_cap(self):
        report = self.offline_plan('--suite', 'exam-v2', '--family', 'gpt',
                                   '--max-output-tokens', '8192', '--stream', '--reasoning-effort', 'high')
        self.assertEqual(report['protocol']['max_output_tokens'], 8192)
        self.assertEqual(report['protocol']['reasoning_effort'], 'high')
        self.assertTrue(report['protocol']['stream'])
        self.assertEqual(report['token_estimate_basis'], 'conservative_reservation_not_billing')
        self.assertEqual(report['total'], {'trials': 220, 'planned_requests': 52800,
                                         'planned_retry_requests': 10560, 'max_requests': 63360,
                                         'estimated_tokens': 794787840})
        self.assertEqual([(stage['phase'], stage['trials'], stage['max_requests']) for stage in report['stages']],
                         [('pilot', 20, 5760), ('validation', 68, 19584),
                          ('validation', 66, 19008), ('validation', 66, 19008)])
        self.assertEqual([(stage['start_trial'], stage['stop_trial']) for stage in report['stages'][1:]],
                         [(0, 34), (34, 67), (67, 100)])
        self.assertTrue(all(stage['date_basis'] == 'UTC' for stage in report['stages']))
        self.assertTrue(report['validation_requires_later_distinct_dates'])
        for trial in report['per_trial']:
            self.assertEqual((trial['planned_requests'], trial['planned_retry_requests'],
                              trial['max_requests'], trial['estimated_tokens']), (240, 48, 288, 3612672))

    def test_deepseek_full_paper_counts_match_independent_size_arithmetic(self):
        output = io.StringIO()
        with patch.object(cli, 'Store', side_effect=AssertionError('budget_store_opened')), \
             patch.object(cli, 'data_directory', side_effect=AssertionError('private_directory_read')), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = cli.main(['calibration-plan', '--primary-model', 'deepseek-primary',
                               '--alternative-model', 'deepseek-alternative', '--wire-api', 'deepseek',
                               '--family', 'deepseek', '--suite', 'exam-v2', '--samples', '180', '--seed', '42'])
        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['family'], 'deepseek')
        self.assertEqual(report['total']['planned_requests'], 79200)
        self.assertEqual(report['total']['planned_retry_requests'], 15840)
        self.assertEqual(report['total']['max_requests'], 95040)
        self.assertEqual(report['per_trial'][0]['max_requests'], 432)
        self.assertEqual(report['per_trial'][0]['estimated_tokens'], 2764800)

    def test_budget_gaps_apply_to_one_trial_without_claiming_existing_spend_is_clear(self):
        report = self.offline_plan('--suite', 'exam-v2', '--request-limit', '280', '--token-limit', '1800000')
        self.assertEqual(report['budget']['state'], 'insufficient')
        self.assertEqual(report['budget'].get('notice'), 'supplied_limits_insufficient')
        self.assertEqual(report['budget']['request_limit'], 280)
        self.assertEqual(report['budget']['token_limit'], 1800000)
        for row in report['budget']['per_trial']:
            self.assertEqual((row['request_gap'], row['token_gap'], row['fits_supplied_limits']), (8, 43200, False))
        partial = self.offline_plan('--suite', 'exam-v2', '--request-limit', '288')
        self.assertEqual(partial['budget']['state'], 'unknown')
        self.assertEqual(partial['budget']['per_trial'][0]['request_gap'], 0)
        self.assertIsNone(partial['budget']['per_trial'][0]['token_gap'])
        self.assertIsNone(partial['budget']['per_trial'][0]['fits_supplied_limits'])
        fits = self.offline_plan('--suite', 'exam-v2', '--request-limit', '288', '--token-limit', '1843200')
        self.assertEqual(fits['budget']['state'], 'fits_supplied_limits')
        self.assertEqual(fits['budget'].get('notice'), 'within_proposed_limits_existing_usage_unchecked')
        self.assertFalse(fits['collection_authorized'])

    def test_suggested_limits_cover_one_whole_trial_without_applying_a_budget(self):
        examples = [
            (['--suite', 'exam-v2', '--samples', '120'], 288, 1843200),
            (['--suite', 'exam-v2', '--samples', '180'], 432, 2764800),
            (['--suite', 'exam-v2', '--max-output-tokens', '1024'], 288, 1548288),
            (['--suite', 'assessment-v4', '--study-scope', 'extended'], 240, 5509120),
            (['--suite', 'assessment-v4', '--family', 'claude', '--wire-api', 'anthropic',
              '--primary-model', 'claude-primary', '--alternative-model', 'claude-alternative'], 240, 921600),
            (['--suite', 'assessment-v4', '--family', 'gemini', '--wire-api', 'gemini',
              '--primary-model', 'gemini-primary', '--alternative-model', 'gemini-alternative'], 240, 921600),
        ]
        for options, requests, tokens in examples:
            with self.subTest(options=options):
                report = self.offline_plan(*options)
                self.assertEqual(report['budget'].get('suggested_limits'), {
                    'request_limit': requests, 'token_limit': tokens,
                    'basis': 'one_complete_trial_including_retries',
                    'applied': False, 'user_confirmation_required': True,
                })
                self.assertEqual(report['budget']['state'], 'unknown')
                self.assertEqual(report['budget']['notice'], 'default_budget_requires_confirmation')
                self.assertIsNone(report['budget']['request_limit'])
                self.assertIsNone(report['budget']['token_limit'])
                self.assertFalse(report['collection_authorized'])
                self.assertIsNone(report['estimated_cost'])
                self.assertEqual(report['currency'], 'unknown')

    def test_suggested_budget_does_not_override_lower_user_limits_or_change_the_trial(self):
        report = self.offline_plan('--suite', 'exam-v2', '--request-limit', '1', '--token-limit', '1',
                                   '--reasoning-effort', 'high')
        self.assertEqual((report['budget']['request_limit'], report['budget']['token_limit']), (1, 1))
        self.assertEqual(report['budget'].get('notice'), 'supplied_limits_insufficient')
        self.assertEqual(report['budget']['suggested_limits']['request_limit'], 288)
        self.assertEqual(report['budget']['suggested_limits']['token_limit'], 1843200)
        self.assertFalse(report['budget']['suggested_limits']['applied'])
        self.assertTrue(report['budget']['suggested_limits']['user_confirmation_required'])
        self.assertEqual(report['samples'], 120)
        self.assertEqual(report['protocol']['reasoning_effort'], 'high')
        for row in report['budget']['per_trial']:
            self.assertEqual((row['request_gap'], row['token_gap']), (287, 1843199))

    def test_compatibility_and_explicit_assessment_have_different_retry_allowances(self):
        compatibility = self.offline_plan()
        explicit = self.offline_plan('--suite', 'assessment-v4')
        self.assertEqual(compatibility['per_trial'][0]['planned_retry_requests'], 0)
        self.assertEqual(explicit['per_trial'][0]['planned_retry_requests'], 160)
        self.assertEqual(compatibility['total']['max_requests'], 17600)
        self.assertEqual(explicit['total']['max_requests'], 52800)
        self.assertEqual(explicit['per_trial'][0]['estimated_tokens'], 921600)

    def test_extended_context_has_separate_bound_without_assessment_retry_allowance(self):
        report = self.offline_plan('--suite', 'assessment-v4', '--study-scope', 'extended')
        context = next(row for row in report['per_trial'] if row['scenario'] == 'context_truncated')
        self.assertEqual((context['planned_requests'], context['planned_retry_requests'],
                          context['max_requests'], context['estimated_tokens']), (80, 0, 80, 5509120))
        self.assertEqual(context['suite_version'], 'context-v1')
        self.assertEqual(report['total']['max_requests'], 167200)

    def test_plan_rejects_invalid_supplied_budgets_without_echoing_inputs(self):
        for option, value in (('--request-limit', '0'), ('--request-limit', '100001'),
                              ('--token-limit', '0'), ('--token-limit', '10000000001')):
            output, error = io.StringIO(), io.StringIO()
            with patch.object(cli, 'Store', side_effect=AssertionError('budget_store_opened')), \
                 patch.object(cli, 'data_directory', side_effect=AssertionError('private_directory_read')), \
                 redirect_stdout(output), redirect_stderr(error):
                status = cli.main(['calibration-plan', '--primary-model', 'gpt-primary',
                                   '--alternative-model', 'gpt-alternative', option, value])
            self.assertEqual(status, 2)
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(error.getvalue().strip(), 'invalid_arguments_or_configuration')

    def test_init_honors_the_explicit_output_cap_in_frozen_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            with patch.object(cli, 'data_directory', return_value=Path(folder)), \
                 patch('relay_auditor.calibration_cli.hidden', side_effect=AssertionError('credential_prompt')), \
                 redirect_stdout(output), redirect_stderr(io.StringIO()):
                status = cli.main(['calibration-init', '--primary-model', 'gpt-primary',
                                   '--alternative-model', 'gpt-alternative', '--max-output-tokens', '8192', '--seed', '42'])
            self.assertEqual(status, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['manifest']['protocol']['max_output_tokens'], 8192)
            persisted = json.loads((Path(folder) / 'studies' / report['study_id'] / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(persisted['protocol']['max_output_tokens'], 8192)

    def test_collect_rejects_changed_explicit_settings_before_key_prompt_or_budget_change(self):
        manifest = calibration.freeze(GPT_PRIMARY, GPT_ALTERNATIVE,
                                      Protocol(max_output_tokens=8192, reasoning_effort='high'), seed=42)
        with tempfile.TemporaryDirectory() as folder:
            study_id = manifest['manifest_hash'][:32]
            directory = Path(folder) / 'studies' / study_id
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            store = Store(folder)
            before = store.budget()
            store.close()
            for changed in (['--max-output-tokens', '2048'], ['--wire-api', 'chat'],
                            ['--stream'], ['--reasoning-effort', 'low']):
                with self.subTest(option=changed[0]):
                    output, error = io.StringIO(), io.StringIO()
                    with patch.object(cli, 'data_directory', return_value=Path(folder)), \
                         patch('relay_auditor.calibration_cli.hidden', side_effect=AssertionError('credential_prompt')), \
                         redirect_stdout(output), redirect_stderr(error):
                        status = cli.main(['calibration-collect', '--study-id', study_id, *changed,
                                           '--request-limit', '1000', '--token-limit', '3000000'])
                    self.assertEqual(status, 2)
                    self.assertEqual(error.getvalue().strip(), 'invalid_arguments_or_configuration')
                    self.assertFalse((directory / 'collect.lock').exists())
                    self.assertFalse((directory / 'outcomes.json').exists())
                    store = Store(folder)
                    try:
                        after = store.budget()
                        self.assertEqual((after['request_limit'], after['token_limit']),
                                         (before['request_limit'], before['token_limit']))
                    finally:
                        store.close()

    def test_collect_accepts_the_same_explicit_cap_and_executes_the_frozen_settings(self):
        from relay_auditor import calibration_cli
        frozen_protocol = Protocol(max_output_tokens=8192, stream=True, reasoning_effort='high')
        manifest = calibration.freeze(GPT_PRIMARY, GPT_ALTERNATIVE, frozen_protocol, seed=42)
        protocols = []

        class SyntheticClient:
            def __init__(self, target): protocols.append(target.protocol)
            def complete(self, case): return Completion(json.dumps({'answer': case.expected}))

        def collect(*args, **kwargs):
            return calibration.collect_trial(*args, **kwargs, client_factory=SyntheticClient, date='2026-11-13')

        with tempfile.TemporaryDirectory() as folder:
            study_id = manifest['manifest_hash'][:32]
            directory = Path(folder) / 'studies' / study_id
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            output = io.StringIO()
            with patch.object(cli, 'data_directory', return_value=Path(folder)), \
                 patch.object(calibration_cli, 'hidden', return_value='synthetic-only'), \
                 patch.object(calibration_cli, 'collect_trial', side_effect=collect), \
                 redirect_stdout(output), redirect_stderr(io.StringIO()):
                status = cli.main(['calibration-collect', '--study-id', study_id, '--max-output-tokens', '8192',
                                   '--wire-api', 'responses', '--stream', '--reasoning-effort', 'high',
                                   '--request-limit', '1000', '--token-limit', '3000000'])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())['requests'], 80)
            self.assertEqual(len(protocols), 80)
            self.assertTrue(all(protocol == frozen_protocol for protocol in protocols))
            self.assertFalse((directory / 'collect.lock').exists())

    def test_native_family_simulation_is_rejected_instead_of_falling_back_to_gpt(self):
        for family in ('claude', 'gemini'):
            output, error = io.StringIO(), io.StringIO()
            with patch.object(cli, 'Store', side_effect=AssertionError('budget_store_opened')), \
                 redirect_stdout(output), redirect_stderr(error):
                status = cli.main(['calibration-simulate', '--family', family, '--suite', 'assessment-v4'])
            self.assertEqual(status, 2)
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(error.getvalue().strip(), 'invalid_arguments_or_configuration')

    def test_native_family_plan_uses_explicit_assessment_and_keeps_their_requested_identity(self):
        for family, wire in (('claude', 'anthropic'), ('gemini', 'gemini')):
            with self.subTest(family=family):
                report = self.offline_plan('--primary-model', family + '-primary',
                                           '--alternative-model', family + '-alternative',
                                           '--family', family, '--wire-api', wire, '--suite', 'assessment-v4')
                self.assertEqual(report['family'], family)
                self.assertEqual(report['protocol']['wire_api'], wire)
                self.assertEqual(report['total']['planned_requests'], 17600)
                self.assertEqual(report['total']['max_requests'], 52800)
                self.assertEqual(report['validation_state'], 'experimental')

    def test_native_plan_rejects_unsupported_scope_suite_and_settings_without_private_reads(self):
        for family, wire in (('claude', 'anthropic'), ('gemini', 'gemini')):
            for changes in (['--suite', 'exam-v2'], ['--study-scope', 'extended'],
                            ['--reasoning-effort', 'low'], ['--wire-api', 'responses']):
                with self.subTest(family=family, option=changes[0]):
                    output, error = io.StringIO(), io.StringIO()
                    with patch.object(cli, 'Store', side_effect=AssertionError('budget_store_opened')), \
                         patch.object(cli, 'data_directory', side_effect=AssertionError('private_directory_read')), \
                         patch('relay_auditor.calibration_cli.hidden', side_effect=AssertionError('credential_prompt')), \
                         redirect_stdout(output), redirect_stderr(error):
                        status = cli.main(['calibration-plan', '--primary-model', family + '-primary',
                                           '--alternative-model', family + '-alternative', '--family', family,
                                           '--wire-api', wire, '--suite', 'assessment-v4', *changes])
                    self.assertEqual(status, 2)
                    self.assertEqual(output.getvalue(), '')
                    self.assertEqual(error.getvalue().strip(), 'invalid_arguments_or_configuration')

    def test_collect_without_overrides_keeps_a_frozen_deepseek_wire(self):
        from relay_auditor import calibration_cli
        frozen_protocol = Protocol(wire_api='deepseek', max_output_tokens=4096)
        manifest = calibration.freeze('deepseek-primary', 'deepseek-alternative', frozen_protocol,
                                      family='deepseek', suite='assessment-v4', seed=42)
        protocols = []

        class SyntheticClient:
            def __init__(self, target): protocols.append(target.protocol)
            def complete(self, case): return Completion(json.dumps({'answer': case.expected}))

        def collect(*args, **kwargs):
            return calibration.collect_trial(*args, **kwargs, client_factory=SyntheticClient, date='2026-11-13')

        with tempfile.TemporaryDirectory() as folder:
            study_id = manifest['manifest_hash'][:32]
            directory = Path(folder) / 'studies' / study_id
            directory.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            output = io.StringIO()
            with patch.object(cli, 'data_directory', return_value=Path(folder)), \
                 patch.object(calibration_cli, 'hidden', return_value='synthetic-only'), \
                 patch.object(calibration_cli, 'collect_trial', side_effect=collect), \
                 redirect_stdout(output), redirect_stderr(io.StringIO()):
                status = cli.main(['calibration-collect', '--study-id', study_id,
                                   '--request-limit', '1000', '--token-limit', '3000000'])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())['requests'], 80)
            self.assertEqual(len(protocols), 80)
            self.assertTrue(all(protocol == frozen_protocol for protocol in protocols))


if __name__ == '__main__': unittest.main()
