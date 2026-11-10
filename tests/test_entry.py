import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest

from relay_auditor.cli import main


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


if __name__ == '__main__':
    unittest.main()
