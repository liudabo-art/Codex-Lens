import json
import unittest

from relay_auditor.protocol import ProbeCase


class GradingTests(unittest.TestCase):
    def grade(self, expected, text):
        from relay_auditor.grading import grade_answer
        return grade_answer(ProbeCase('synthetic', 1, 'synthetic', expected), text)

    def test_unique_json_is_recovered_without_using_expected_to_choose(self):
        for text in ('{"answer":{"ids":[1,2],"total":3}}',
                     '{"ids":[1,2],"total":3}',
                     '```json\n{"answer":{"ids":[1,2],"total":3}}\n```',
                     'The computed result follows.\n{"answer":{"ids":[1,2],"total":3}}\nDone.'):
            with self.subTest(text=text):
                actual = self.grade({'ids': [1, 2], 'total': 3}, text)
                self.assertTrue(actual['correct'])
                self.assertEqual(actual['format_state'], 'valid' if text.startswith('{"answer"') else 'recovered_format')
        wrong = self.grade(7, 'Result: {"answer":8}.')
        self.assertFalse(wrong['correct'])
        self.assertEqual(wrong['format_state'], 'recovered_format')

    def test_ambiguous_duplicate_and_invalid_candidates_are_not_salvaged(self):
        examples = [
            ('{"answer":7} {"answer":8}', 'ambiguous_answer'),
            ('{"answer":7} {"answer":7}', 'ambiguous_answer'),
            ('{"answer":7} 8', 'ambiguous_answer'),
            ('{"answer":7}\n```json\n8\n```', 'ambiguous_answer'),
            ('{"answer":7,"answer":8}', 'duplicate_keys'),
            ('Before {"answer":{"total":7,"total":8}}', 'duplicate_keys'),
            ('{"answer":7} trailing {"answer":', 'invalid_json'),
            ('The answer is seven.', 'missing_answer'),
            ('{"answer":NaN}', 'nonfinite_number'),
            ('{"answer":1e999}', 'nonfinite_number'),
            (' '.join(['{"answer":7}'] * 9), 'too_many_candidates'),
        ]
        for text, issue in examples:
            with self.subTest(issue=issue):
                grade = self.grade(7, text)
                self.assertIsNone(grade['correct'])
                self.assertEqual(grade['error_code'], 'answer_format')
                self.assertEqual(grade['grading_issue'], issue)

    def test_incidental_prose_numbers_are_not_treated_as_alternate_json_answers(self):
        for text in ('For question 1, result is {"answer":7}.',
                     'Result:\n{"answer":7}\nThis uses 2 intermediate steps.',
                     'The single answer for 2026 is:\n```json\n{"answer":7}\n```'):
            with self.subTest(text=text):
                grade = self.grade(7, text)
                self.assertTrue(grade['correct'])
                self.assertEqual(grade['format_state'], 'recovered_format')

    def test_multiple_standalone_scalar_roots_do_compete_with_json(self):
        for text in ('{"answer":7} 8 9', '{"answer":7} true false',
                     '8 9\n{"answer":7}', '{"answer":7}\n8 9'):
            with self.subTest(text=text):
                self.assertEqual(self.grade(7, text)['grading_issue'], 'ambiguous_answer')

    def test_missing_nested_fields_and_boolean_integer_coercion_fail_format(self):
        for expected, text, issue in [
            ({'total': 1, 'ids': []}, '{"answer":{"total":1}}', 'missing_fields'),
            ({'total': 1}, '{"answer":{"total":1,"extra":0}}', 'unexpected_fields'),
            ({'meta': {'count': 1}}, '{"answer":{"meta":{}}}', 'missing_fields'),
            (1, '{"answer":true}', 'answer_type'),
            (1, '{"answer":1.0}', 'answer_type'),
            ({'columns': [{'cells': []}, {'cells': [{'row': 1, 'value': 2}]}]},
             '{"answer":{"columns":[{"cells":[{"row":1}]}]}}', 'missing_fields'),
        ]:
            with self.subTest(issue=issue):
                self.assertEqual(self.grade(expected, text)['grading_issue'], issue)

    def test_parser_bounds_and_string_braces(self):
        from relay_auditor.grading import MAX_ANSWER_BYTES, MAX_JSON_DEPTH
        self.assertEqual(self.grade(1, 'x' * (MAX_ANSWER_BYTES + 1))['grading_issue'], 'answer_too_large')
        deep = '[' * (MAX_JSON_DEPTH + 1) + '0' + ']' * (MAX_JSON_DEPTH + 1)
        self.assertEqual(self.grade([], deep)['grading_issue'], 'answer_too_deep')
        grade = self.grade({'text': '} [ {'}, 'Output: {"answer":{"text":"} [ {"}} Done.')
        self.assertTrue(grade['correct'])


if __name__ == '__main__':
    unittest.main()
