import json
from pathlib import Path
import tempfile
import unittest

from relay_auditor.controller import Service
from relay_auditor.protocol import Protocol, PROBE_KINDS
from relay_auditor.storage import Store
from relay_auditor.transport import Completion


class FakeClient:
    calls = []
    interrupt = None

    def __init__(self, target):
        self.target = target

    def complete(self, case):
        self.calls.append((self.target.role, case.kind))
        if self.interrupt:
            callback = type(self).interrupt
            type(self).interrupt = None
            callback()
        if case.kind == 'sequence':
            text = json.dumps({'numbers': [[7] * 35 for _ in range(9)]})
        elif case.kind in PROBE_KINDS:
            values = {'coin': 'heads', 'digit': '7', 'dice': '3', 'color': 'blue', 'weekday': 'monday'}
            text = values[case.kind]
        else:
            text = json.dumps({'answer': case.expected})
        return Completion(text, {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data'
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        FakeClient.calls = []
        FakeClient.interrupt = None
        self.service = Service(self.store, client_factory=FakeClient, clock=lambda: 10000)
        self.alias = self.service.configure('https://relay.example/v1', 'PRIVATE-KEY', 'model-a',
                                            Protocol(), reference_key='PRIVATE-OFFICIAL')

    def test_off_by_default_no_network_on_configure_or_tick(self):
        self.service.tick()
        self.assertEqual(FakeClient.calls, [])
        self.assertFalse(self.service.snapshot()['targets'][0]['enabled'])

    def test_manual_screen_has_three_calls_and_never_certifies_without_baseline(self):
        result = self.service.run(self.alias, 'screen')
        self.assertEqual(len(FakeClient.calls), 3)
        self.assertEqual(result['identity_state'], 'baseline_missing')
        self.assertEqual(result['capability_correct'], 2)
        self.assertEqual(self.service.snapshot()['budget']['requests'], 3)
        rendered = json.dumps(self.service.snapshot())
        self.assertNotIn('PRIVATE', rendered)
        self.assertNotIn('relay.example', rendered)

    def test_disabling_inflight_run_stops_followup_requests(self):
        self.service.control(self.alias, enabled=True, active_only=False)
        FakeClient.interrupt = lambda: self.service.control(self.alias, enabled=False)
        self.service.run(self.alias, 'screen')
        self.assertEqual(len(FakeClient.calls), 1)
        self.assertFalse(self.service.snapshot()['targets'][0]['enabled'])

    def test_interval_and_activity_gate_only_affect_future_schedule(self):
        self.service.control(self.alias, enabled=True, interval_seconds=42, active_only=True)
        self.assertFalse(self.service.due(self.alias, 10000))
        self.service.mark_active(self.alias, 10000)
        self.assertTrue(self.service.due(self.alias, 10000))
        self.service.run(self.alias, 'screen')
        self.assertFalse(self.service.due(self.alias, 10041))
        self.assertTrue(self.service.due(self.alias, 10042))
        self.service.control(self.alias, interval_seconds=100)
        self.assertFalse(self.service.due(self.alias, 10042))
        self.assertEqual(self.service.snapshot()['budget']['requests'], 3)

    def test_request_limit_stops_calls_instead_of_returning_zero_cost(self):
        self.store.set_limits(2, 100000)
        result = self.service.run(self.alias, 'screen')
        self.assertEqual(len(FakeClient.calls), 2)
        self.assertEqual(result['status'], 'budget_exhausted')

    def test_baseline_is_protocol_matched_and_experimental(self):
        self.service.run(self.alias, 'baseline', samples=12)
        result = self.service.run(self.alias, 'screen')
        self.assertEqual(result['identity_state'], 'screening_consistent')
        self.assertEqual(result['validation_state'], 'experimental')

    def test_formal_audit_requires_budget_before_sending_any_request(self):
        result = self.service.run(self.alias, 'identity_audit')
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(FakeClient.calls, [])

    def test_formal_audit_collects_fresh_reference_and_uses_persistent_alpha(self):
        result = self.service.run(self.alias, 'identity_audit', samples=2)
        self.assertEqual(len(FakeClient.calls), 20)
        self.assertEqual(result['identity_state'], 'insufficient_data')
        # A tiny transport test must not accidentally yield a strong verdict.
        self.assertEqual(result['audit_index'], 1)
        self.service.control(self.alias, enabled=False, interval_seconds=30)
        self.assertAlmostEqual(self.store.next_audit()[1], 0.01 / 6)

    def test_budget_and_audit_sequence_survive_restart_without_saving_secrets(self):
        self.service.run(self.alias, 'screen')
        self.store.next_audit()
        second = Store(self.path)
        self.addCleanup(second.close)
        self.assertEqual(second.budget()['requests'], 3)
        self.assertEqual(second.next_audit()[0], 2)
        for file in self.path.iterdir():
            if file.is_file():
                raw = file.read_bytes()
                self.assertNotIn(b'PRIVATE', raw)
                self.assertNotIn(b'relay.example', raw)

    def test_unknown_usage_keeps_estimate_reserved(self):
        ticket = self.store.reserve(2000)
        self.store.settle(ticket, None)
        self.assertEqual(self.store.budget()['estimated_tokens'], 2000)
        self.assertEqual(self.store.budget()['unknown_usage_requests'], 1)

    def test_auto_dispatch_rechecks_disable_before_begin(self):
        self.service.control(self.alias, enabled=True, active_only=False)
        original = self.service.submit
        def interleave(*args, **kwargs):
            self.service.control(self.alias, enabled=False)
            return original(*args, **kwargs)
        self.service.submit = interleave
        self.service.tick()
        import time
        time.sleep(0.05)
        self.assertEqual(FakeClient.calls, [])

    def test_baseline_lookup_binds_explicit_reference_model(self):
        self.service.run(self.alias, 'baseline', samples=12)
        other = self.service.configure('https://another-relay.example/v1', 'k', 'model-a', Protocol(),
                                       reference_key='reference', reference_model='different-reference')
        result = self.service.run(other, 'screen')
        self.assertEqual(result['identity_state'], 'baseline_missing')
        self.assertEqual(result['reference_model'], 'different-reference')

    def test_format_failure_is_not_all_correct(self):
        class InvalidClient(FakeClient):
            def complete(self, case):
                if case.kind == 'logic':
                    return Completion('PRIVATE-RAW', {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2})
                return super().complete(case)
        self.service.client_factory = InvalidClient
        result = self.service.run(self.alias, 'screen')
        self.assertEqual(result['capability_state'], 'incomplete_comparison')
        self.assertEqual(result['accuracy'], 0.5)

    def test_cancelled_formal_run_preserves_audit_index_and_releases_unsent_budget(self):
        FakeClient.interrupt = lambda: self.service.control(self.alias, enabled=False)
        result = self.service.run(self.alias, 'identity_audit', samples=2)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['audit_index'], 1)
        self.assertEqual(result['response_count'], 1)
        self.assertEqual(self.store.budget()['held_requests'], 0)
        self.assertEqual(self.store.budget()['requests'], 1)

    def test_reserved_batch_cannot_be_spent_by_other_store_connection(self):
        self.store.set_limits(2, 10000)
        ticket = self.store.reserve_batch(2, 2000)
        other = Store(self.path)
        self.addCleanup(other.close)
        from relay_auditor.storage import BudgetExceeded
        with self.assertRaises(BudgetExceeded):
            other.reserve(100)
        with self.assertRaises(ValueError):
            other.set_limits(1, 10000)
        first = self.store.reserve(1500, batch=ticket)
        self.store.settle(first, None)
        self.store.release_batch(ticket)
        self.assertEqual(self.store.budget()['held_requests'], 0)
        self.assertTrue(other.available(1, 2000))


if __name__ == '__main__':
    unittest.main()
