"""Explicit CLI selection binds an exact paper and never authorizes a fallback."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relay_auditor import calibration, calibration_cli, cli
from relay_auditor.core import Auditor
from relay_auditor.protocol import Protocol
from relay_auditor.storage import Store


class ExactStudyCLISelectionTests(unittest.TestCase):
    def prepare(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(temporary.name)
        self.addCleanup(store.close)
        manifest = calibration.freeze('claude-primary', 'claude-alternative', Protocol(wire_api='anthropic'),
                                      family='claude', suite='claude-exam-v1', samples=120, seed=42)
        study_id = manifest['manifest_hash'][:32]
        root = Path(temporary.name) / 'studies' / study_id
        root.mkdir(parents=True)
        (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        args = SimpleNamespace(command='calibration-collect', study_id=study_id,
                               wire_api_explicit=False, wire_api='responses', stream=False,
                               reasoning_effort=None, max_output_tokens=None,
                               suite=None, family=None, samples=None, seed=None,
                               primary_model=None, alternative_model=None,
                               scenario='healthy', phase='pilot', trial=0,
                               request_limit=1000, token_limit=10_000_000)
        return args, manifest, store, root

    def test_conflicting_frozen_inputs_reject_before_budget_change_or_key_prompt(self):
        for field, value in (('family', 'gpt'), ('suite', 'exam-v2'), ('samples', 180), ('seed', 43),
                             ('primary_model', 'claude-other'), ('alternative_model', 'claude-other')):
            with self.subTest(field=field):
                args, _, store, root = self.prepare()
                before = store.budget()
                setattr(args, field, value)
                with patch.object(calibration_cli, 'hidden', side_effect=AssertionError('unexpected_key_prompt')):
                    with self.assertRaisesRegex(ValueError, 'study_targets_mismatch'):
                        calibration_cli.command(args, store)
                after = store.budget()
                self.assertEqual((after['request_limit'], after['token_limit']),
                                 (before['request_limit'], before['token_limit']))
                self.assertFalse((root / 'collect.lock').exists())
                self.assertFalse((root / 'outcomes.json').exists())

    def test_matching_explicit_frozen_inputs_preserve_the_requested_manifest(self):
        args, manifest, store, root = self.prepare()
        for field in ('family', 'samples', 'seed', 'primary_model', 'alternative_model'):
            setattr(args, field, manifest[field])
        args.suite = manifest['suite_version']
        with patch.object(calibration_cli, 'hidden', return_value='synthetic-only'), \
             patch.object(calibration_cli, 'collect_trial', return_value={'synthetic': True}) as collect:
            self.assertEqual(calibration_cli.command(args, store), {'synthetic': True})
        self.assertEqual(collect.call_args.args[0], manifest)
        self.assertFalse((root / 'collect.lock').exists())


class ExactExamCLISelectionTests(unittest.TestCase):
    def invoke(self, command, selection, *, mode=None, family='claude'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        auditor = Auditor(temporary.name)
        alias = auditor.configure('https://synthetic.invalid/v1', 'synthetic-only', family + '-primary',
                                  Protocol(wire_api={'claude': 'anthropic', 'gemini': 'gemini'}[family]))
        output, error = io.StringIO(), io.StringIO()
        arguments = [command, '--target', alias, *selection]
        if mode:
            arguments.extend(['--mode', mode])
        with patch.object(cli, 'data_directory', return_value=Path(temporary.name)), \
             patch.object(cli, 'Auditor', return_value=auditor), \
             patch.object(auditor.service, 'run', side_effect=AssertionError('unauthorized_exam_run')), \
             redirect_stdout(output), redirect_stderr(error):
            status = cli.main(arguments)
        return status, output.getvalue(), error.getvalue()

    def test_mismatched_explicit_family_or_suite_rejects_before_preview_or_run(self):
        for command, mode in (('capability-exam', None), ('estimate', 'capability_exam')):
            for selection in (['--family', 'gpt'], ['--suite', 'exam-v2']):
                with self.subTest(command=command, selection=selection):
                    status, output, error = self.invoke(command, selection, mode=mode)
                    self.assertEqual(status, 2)
                    self.assertEqual(output, '')
                    self.assertEqual(error.strip(), 'invalid_arguments_or_configuration')

    def test_matching_explicit_family_and_suite_accept_the_selected_preview(self):
        selection = ['--family', 'claude', '--suite', 'claude-exam-v1']
        for command, mode in (('capability-exam', None), ('estimate', 'capability_exam')):
            with self.subTest(command=command):
                status, output, error = self.invoke(command, selection, mode=mode)
                self.assertEqual(status, 2 if command == 'capability-exam' else 0)
                report = json.loads(error if command == 'capability-exam' else output)
                self.assertEqual((report['model_family'], report['suite_version']), ('claude', 'claude-exam-v1'))

    def test_gemini_preview_matches_its_own_paper_and_rejects_cross_family_selection(self):
        for command, mode in (('capability-exam', None), ('estimate', 'capability_exam')):
            with self.subTest(command=command):
                status, output, error = self.invoke(command, ['--family', 'gemini', '--suite', 'gemini-exam-v1'],
                                                    mode=mode, family='gemini')
                self.assertEqual(status, 2 if command == 'capability-exam' else 0)
                report = json.loads(error if command == 'capability-exam' else output)
                self.assertEqual((report['model_family'], report['suite_version']), ('gemini', 'gemini-exam-v1'))
                status, output, error = self.invoke(command, ['--family', 'gemini', '--suite', 'claude-exam-v1'],
                                                    mode=mode, family='gemini')
                self.assertEqual((status, output, error.strip()), (2, '', 'invalid_arguments_or_configuration'))

    def test_four_family_offline_study_plans_preserve_selected_sizes_suites_and_bounds(self):
        for family, wire, suite, bound in (('gpt', 'responses', 'exam-v2', 6400),
                                          ('deepseek', 'deepseek', 'exam-v2', 6400),
                                          ('claude', 'anthropic', 'claude-exam-v1', 10496),
                                          ('gemini', 'gemini', 'gemini-exam-v1', 10496)):
            for samples in (120, 180):
                with self.subTest(family=family, samples=samples):
                    output = io.StringIO()
                    with patch.object(cli, 'data_directory', side_effect=AssertionError('private_directory_read')), \
                         patch.object(cli, 'Store', side_effect=AssertionError('private_store_opened')), \
                         patch('relay_auditor.transport.APIClient.__init__', side_effect=AssertionError('real_api_client')), \
                         redirect_stdout(output), redirect_stderr(io.StringIO()):
                        status = cli.main(['calibration-plan', '--family', family, '--wire-api', wire,
                                           '--suite', suite, '--primary-model', family + '-primary',
                                           '--alternative-model', family + '-alternative', '--samples', str(samples),
                                           '--seed', '42'])
                    self.assertEqual(status, 0)
                    plan = json.loads(output.getvalue())
                    self.assertEqual((plan['family'], plan['suite_version'], plan['samples']), (family, suite, samples))
                    self.assertEqual({row['per_call'] for row in plan['per_trial']}, {bound})
                    self.assertEqual(plan['real_api_requests'], 0)


if __name__ == '__main__':
    unittest.main()
