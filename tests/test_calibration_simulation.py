import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from relay_auditor import cli


def run_offline():
    output = io.StringIO()
    with patch.object(cli, 'data_directory', side_effect=AssertionError('accessed local data')), \
         patch.object(cli, 'Auditor', side_effect=AssertionError('loaded live auditor')), \
         patch.object(cli, 'Store', side_effect=AssertionError('opened data store')), \
         patch.object(cli, 'hidden', side_effect=AssertionError('requested credentials')), \
         redirect_stdout(output), redirect_stderr(io.StringIO()):
        status = cli.main(['calibration-simulate', '--trials', '8', '--seed', '42'])
    return status, output.getvalue()


class SimulationTests(unittest.TestCase):
    def test_simulates_each_scenario_and_sample_budget_without_loading_local_data(self):
        status, raw = run_offline()
        self.assertEqual(status, 0)
        report = json.loads(raw)
        self.assertEqual(report['evidence'], 'synthetic_simulation')
        self.assertEqual(report['suite_version'], 'assessment-v4')
        self.assertEqual(report['real_api_requests'], 0)
        rows = report['paired']
        self.assertEqual({row['pairs'] for row in rows}, {40, 80, 120, 200})
        self.assertEqual({row['scenario'] for row in rows}, {
            'healthy', 'minor_loss', 'weak_substitution', 'reasoning_changed',
            'mixed_10', 'mixed_30', 'mixed_50', 'context_truncated',
        })
        self.assertEqual({row['missingness'] for row in rows}, {
            'none', 'symmetric', 'relay_only', 'failure_biased',
        })
        self.assertEqual(len(rows), 128)
        for row in rows:
            self.assertEqual(sum(row['verdicts'].values()), 8)
            self.assertEqual(row['paired_attempts'], row['pairs'] * 8)
            self.assertTrue(0 <= row['valid_pair_fraction'] <= 1)
            self.assertTrue(0 <= row['decision_ready_fraction'] <= 1)
            lower, upper = row['mean_missingness_loss_bounds']
            self.assertLessEqual(lower, upper)
            if row['missingness'] == 'none':
                self.assertEqual(row['valid_pair_fraction'], 1)
                self.assertEqual(row['decision_ready_fraction'], 1)
                self.assertEqual(lower, upper)
        self.assertEqual(run_offline(), (status, raw))

    def test_no_reference_simulation_exercises_four_round_history_and_abstention(self):
        status, raw = run_offline()
        self.assertEqual(status, 0)
        histories = json.loads(raw)['no_reference']
        self.assertEqual(histories['stable']['trend']['status'], 'no_detected_deviation')
        self.assertEqual(histories['sustained_decline']['trend']['status'], 'historical_decline_signal')
        self.assertEqual(histories['one_failed_round']['trend']['status'], 'not_comparable')
        for history in histories.values():
            self.assertEqual(len(history['rounds']), 4)
            self.assertTrue(all(row['reference_requests'] == 0 for row in history['rounds']))
        self.assertEqual(histories['one_failed_round']['rounds'][-1]['valid'], 9)


if __name__ == '__main__':
    unittest.main()
