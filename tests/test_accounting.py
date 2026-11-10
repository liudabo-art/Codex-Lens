import unittest

from relay_auditor.accounting import group_usage


class SourceAccountingTests(unittest.TestCase):
    def test_same_model_separates_official_login_and_each_relay(self):
        rows = [
            {'model': 'gpt-test', 'input_tokens': 10, 'output_tokens': 5,
             'source_evidence': {'scope': 'request', 'auth_mode': 'chatgpt', 'destination': 'official'}},
            {'model': 'gpt-test', 'input_tokens': 20, 'output_tokens': 5,
             'source_evidence': {'scope': 'request', 'auth_mode': 'api_key', 'destination': 'relay', 'provider': 'PRIVATE-A'}},
            {'model': 'gpt-test', 'input_tokens': 30, 'output_tokens': 5,
             'source_evidence': {'scope': 'request', 'auth_mode': 'api_key', 'destination': 'relay', 'provider': 'PRIVATE-B'}},
        ]
        result = group_usage(rows)
        self.assertEqual(result['official_login']['total_tokens'], 15)
        self.assertEqual(result['relay']['total_tokens'], 60)
        self.assertEqual([r['total_tokens'] for r in result['relay_providers']], [25, 35])
        self.assertNotIn('PRIVATE', str(result))

    def test_current_login_or_config_does_not_attribute_historical_usage(self):
        rows = [{'input_tokens': 100, 'output_tokens': 10, 'source_evidence':
                 {'scope': 'current_configuration', 'auth_mode': 'chatgpt', 'destination': 'official'}}]
        result = group_usage(rows)
        self.assertEqual(result['unknown']['total_tokens'], 110)
        self.assertEqual(result['official_login']['total_tokens'], 0)

    def test_cached_official_login_does_not_override_recorded_relay_destination(self):
        result = group_usage([{'input_tokens': 7, 'output_tokens': 3, 'source_evidence':
                               {'scope': 'request', 'auth_mode': 'chatgpt', 'destination': 'relay', 'provider': 'PRIVATE-A'}}])
        self.assertEqual(result['relay']['total_tokens'], 10)
        self.assertEqual(result['official_login']['total_tokens'], 0)

    def test_official_api_reference_never_becomes_official_login_or_business(self):
        result = group_usage([{'input_tokens': 8, 'output_tokens': 2, 'purpose': 'reference',
                               'source_evidence': {'scope': 'request', 'auth_mode': 'api_key', 'destination': 'official'}}])
        self.assertEqual(result['reference']['total_tokens'], 10)
        self.assertEqual(result['official_login']['total_tokens'], 0)
        self.assertEqual(result['relay']['total_tokens'], 0)

    def test_cached_and_reasoning_tokens_are_subsets_not_added_twice(self):
        result = group_usage([{'input_tokens': 100, 'output_tokens': 30, 'cached_input_tokens': 70,
                              'reasoning_output_tokens': 20}])
        self.assertEqual(result['unknown']['total_tokens'], 130)

    def test_missing_usage_is_not_a_zero_token_record(self):
        result = group_usage([{'model':'gpt-test'}])
        self.assertEqual(result['invalid_records'], 1)
        self.assertEqual(result['unknown']['record_count'], 0)


if __name__ == '__main__':
    unittest.main()
