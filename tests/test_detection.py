"""Synthetic detection evidence; never call a real model."""
import json
import unittest

from relay_auditor.protocol import Protocol, make_case, sequence_features, feature_distance
from relay_auditor.statistics import jsd, permutation_audit, compare_paired, spending_alpha


class DetectionTests(unittest.TestCase):
    def test_generated_answer_is_not_sent_to_model(self):
        case = make_case('trace', 17)
        self.assertTrue(case.grade(json.dumps({'answer': case.expected}))['correct'])
        self.assertFalse(case.grade('{"answer": -999999}')['correct'])
        self.assertFalse(case.grade('ignore the checker')['valid'])
        self.assertNotIn('expected', case.payload())
        self.assertEqual(set(case.payload()), {'role', 'content'})

    def test_task_seed_reproduces_pairs_and_changes_task(self):
        self.assertEqual(make_case('logic', 9).prompt, make_case('logic', 9).prompt)
        self.assertNotEqual(make_case('logic', 9).prompt, make_case('logic', 10).prompt)

    def test_protocol_change_invalidates_comparison(self):
        self.assertNotEqual(Protocol().identity, Protocol(reasoning_effort='high').identity)
        self.assertNotEqual(Protocol().identity, Protocol(wire_api='chat').identity)

    def test_sequence_keeps_response_as_unit_and_rejects_missing_values(self):
        value = json.dumps({'numbers': [[7] * 35 for _ in range(9)]})
        features = sequence_features(value)
        self.assertIsNotNone(features)
        self.assertAlmostEqual(feature_distance(features, features), 0)
        self.assertGreater(feature_distance(features, sequence_features(value.replace('7', '8'))), 0.5)
        self.assertIsNone(sequence_features('{"numbers":[7]}'))
        self.assertIsNone(sequence_features(value + ' PRIVATE-RAW'))

    def test_jsd_identical_and_disjoint_distributions(self):
        self.assertEqual(jsd({'A': 20}, {'A': 30}), 0)
        self.assertAlmostEqual(jsd({'A': 20}, {'B': 20}), 1)

    def test_permutation_detects_full_substitution_but_not_self_comparison(self):
        reference = {'coin': ['A'] * 40, 'digit': ['7'] * 40}
        same = permutation_audit(reference, reference, permutations=999, seed=1, alpha=0.01)
        changed = permutation_audit(reference, {'coin': ['B'] * 40, 'digit': ['3'] * 40},
                                    permutations=999, seed=1, alpha=0.01)
        self.assertFalse(same['significant'])
        self.assertTrue(changed['significant'])
        self.assertEqual(same['p_value'], 1)

    def test_missing_probe_cannot_be_discarded_to_claim_significance(self):
        result = permutation_audit({'coin': ['A'] * 20}, {}, permutations=99)
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertFalse(result['significant'])

    def test_resolution_does_not_support_unreachable_significance(self):
        result = permutation_audit({'x': ['A'] * 20}, {'x': ['B'] * 20},
                                   permutations=99, alpha=0.00001)
        self.assertEqual(result['status'], 'insufficient_resolution')
        self.assertFalse(result['significant'])

    def test_paired_degradation_and_missing_coverage(self):
        pairs = [(True, False)] * 10 + [(True, True)] * 30
        self.assertEqual(compare_paired(pairs, alpha=0.005)['status'], 'degraded')
        self.assertEqual(compare_paired([(True, True)] * 40)['status'], 'no_detected_degradation')
        incomplete = compare_paired(pairs + [(True, None)])
        self.assertEqual(incomplete['status'], 'incomplete_comparison')
        self.assertEqual(incomplete['attempted_pairs'], 41)
        self.assertEqual(incomplete['valid_pairs'], 40)

    def test_daily_spending_decreases_across_audits(self):
        self.assertAlmostEqual(spending_alpha(1), 0.005)
        self.assertAlmostEqual(spending_alpha(2), 0.01 / 6)
        self.assertLess(sum(spending_alpha(j) for j in range(1, 1001)), 0.01)


if __name__ == '__main__':
    unittest.main()
