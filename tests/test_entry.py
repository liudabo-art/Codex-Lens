import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from relay_auditor.cli import main
from relay_auditor.core import Auditor
from relay_auditor.protocol import Protocol
from test_service import FakeClient


class EntryTests(unittest.TestCase):
    def test_help_does_not_start_service_or_create_output(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(main(['--help']), 0)
        self.assertIn('serve', out.getvalue())

    def test_unknown_arguments_are_not_echoed_to_terminal(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(main(['--PRIVATE-KEY']), 2)
        self.assertNotIn('PRIVATE-KEY', out.getvalue())

    def test_saved_target_output_limit_changes_only_when_explicit(self):
        for output_limit in (None, 8192):
            with self.subTest(output_limit=output_limit), tempfile.TemporaryDirectory() as directory:
                with Auditor(directory, client_factory=FakeClient) as auditor:
                    alias = auditor.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test',
                                                Protocol(max_output_tokens=4096, reasoning_effort='high'))
                    out = io.StringIO()
                    arguments = ['estimate', '--mode', 'capability_exam', '--target', alias]
                    if output_limit is not None:
                        arguments += ['--max-output-tokens', str(output_limit)]
                    with patch('relay_auditor.cli.Auditor', return_value=auditor), \
                            patch('relay_auditor.cli.data_directory', return_value=directory), redirect_stdout(out), redirect_stderr(out):
                        self.assertEqual(main(arguments), 0)
                    protocol = auditor.service.monitors[alias].target.protocol
                    self.assertEqual(protocol.max_output_tokens, output_limit or 4096)
                    self.assertEqual(protocol.reasoning_effort, 'high')
                    self.assertEqual(json.loads(out.getvalue())['max_output_tokens'], output_limit or 4096)

    def test_output_limit_is_validated_before_opening_settings(self):
        for output_limit in ('127', '16385'):
            out = io.StringIO()
            with patch('relay_auditor.cli.Auditor', side_effect=AssertionError('opened settings')) as owner, \
                    redirect_stdout(out), redirect_stderr(out):
                self.assertEqual(main(['estimate', '--max-output-tokens', output_limit]), 2)
            owner.assert_not_called()

    def test_new_target_cli_uses_explicit_output_limit(self):
        with tempfile.TemporaryDirectory() as directory, Auditor(directory, client_factory=FakeClient) as auditor:
            out = io.StringIO()
            with patch('relay_auditor.cli.Auditor', return_value=auditor), \
                    patch('relay_auditor.cli.data_directory', return_value=directory), \
                    patch('relay_auditor.cli.hidden', side_effect=['https://relay.invalid/v1', 'synthetic', '']), \
                    patch('builtins.input', return_value='gpt-test'), redirect_stdout(out), redirect_stderr(out):
                self.assertEqual(main(['estimate', '--mode', 'capability_exam', '--max-output-tokens', '8192']), 0)
            self.assertEqual(json.loads(out.getvalue())['max_output_tokens'], 8192)


if __name__ == '__main__':
    unittest.main()
