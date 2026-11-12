import http.client
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from relay_auditor.controller import Service
from relay_auditor.server import make_server
from relay_auditor.storage import Store, safe_snapshot
from test_service import FakeClient


class HistoryDeletionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = Store(self.directory / 'data')
        self.addCleanup(self.store.close)
        self.service = Service(self.store, client_factory=FakeClient)
        self.addCleanup(self.service.stop)
        self.alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')

    def record(self, **changes):
        row = {'schema_version': 2, 'target_id': self.service.monitors[self.alias].target_id,
               'model': 'gpt-test', 'source_alias': self.alias, 'mode': 'quality', 'status': 'ok'} | changes
        row['record_id'] = self.store.record(row)
        return row

    def test_duplicate_payloads_have_stable_distinct_ids_and_keep_integer_order(self):
        first, second = self.record(), self.record()
        self.assertIsInstance(first['record_id'], str)
        self.assertEqual(uuid.UUID(first['record_id']).hex, first['record_id'])
        self.assertNotEqual(first['record_id'], second['record_id'])
        self.assertEqual([row['record_id'] for row in self.store.history()],
                         [second['record_id'], first['record_id']])
        restarted = Store(self.directory / 'data')
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.history(), self.store.history())
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute('INSERT INTO results(record_id,data) VALUES (?,?)',
                                          (first['record_id'], '{}'))

    def test_recorded_result_and_card_share_id_without_echoing_supplied_ids(self):
        result = self.service.run(self.alias, 'quality', samples=1)
        self.assertIn('record_id', result)
        self.assertEqual(result['record_id'], self.store.history()[0]['record_id'])
        self.assertEqual(result['record_id'], self.service.snapshot()['targets'][0]['last_result']['record_id'])
        supplied = uuid.uuid4().hex
        self.assertNotEqual(self.record(record_id=supplied)['record_id'], supplied)

    def test_single_batch_duplicates_and_nonexistent_ids_are_idempotent(self):
        first, second, third = self.record(), self.record(), self.record()
        removed = self.service.delete_history(record_ids=[first['record_id'], first['record_id'], uuid.uuid4().hex])
        self.assertEqual(removed, {'deleted_count': 1, 'total_remaining': 2})
        self.assertEqual(self.service.delete_history(record_ids=[first['record_id']]),
                         {'deleted_count': 0, 'total_remaining': 2})
        self.assertEqual(self.service.delete_history(record_ids=[second['record_id'], third['record_id']]),
                         {'deleted_count': 2, 'total_remaining': 0})

    def test_all_deletes_beyond_visible_200_without_reusing_uuid(self):
        rows = [self.record() for _ in range(205)]
        state = self.service.snapshot()
        self.assertEqual(len(state['history']), 200)
        self.assertEqual(state['history_count'], 205)
        self.assertEqual(self.service.delete_history(all=True), {'deleted_count': 205, 'total_remaining': 0})
        self.assertEqual(self.service.snapshot()['history_count'], 0)
        self.assertNotIn(self.record()['record_id'], {row['record_id'] for row in rows})
        self.assertEqual(self.service.delete_history(all=True), {'deleted_count': 1, 'total_remaining': 0})

    def test_malformed_batch_rejects_every_member(self):
        row = self.record()
        for options in ({}, {'record_ids': []}, {'record_ids': row['record_id']},
                        {'record_ids': [row['record_id'], 'invalid']}, {'record_ids': [1]},
                        {'record_ids': [True]}, {'record_ids': [None]}, {'all': False}, {'all': 1},
                        {'record_ids': [row['record_id']], 'all': True}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, '^invalid_history_delete$'):
                self.service.delete_history(**options)
            self.assertEqual(self.store.history_count(), 1)

    def test_busy_or_pending_deletion_is_rejected_before_storage_or_cache_change(self):
        row = self.record()
        monitor = self.service.monitors[self.alias]
        monitor.last_result = row
        for busy, pending in ((True, []), (False, ['synthetic-queued'])):
            self.service.busy, self.service.pending = busy, pending
            with self.assertRaisesRegex(ValueError, '^history_busy$'):
                self.service.delete_history(record_ids=[row['record_id']])
            self.assertIs(monitor.last_result, row)
            self.assertEqual(self.store.history_count(), 1)
        self.service.busy, self.service.pending = False, []

    def test_deleting_matching_cache_does_not_restore_an_older_card(self):
        older, current, unrelated = self.record(), self.record(), self.record()
        monitor = self.service.monitors[self.alias]
        monitor.last_result = current
        monitor.previous_non_exam_result = older
        self.service.delete_history(record_ids=[unrelated['record_id']])
        self.assertIs(monitor.last_result, current)
        self.service.delete_history(record_ids=[current['record_id']])
        self.assertIsNone(monitor.last_result)
        self.assertIs(monitor.previous_non_exam_result, older)
        self.assertIsNone(self.service.snapshot()['targets'][0]['last_result'])
        self.service.delete_history(record_ids=[older['record_id']])
        self.assertIsNone(monitor.previous_non_exam_result)
        restarted = Service(self.store, client_factory=FakeClient)
        alias = restarted.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
        self.assertIsNone(restarted.monitors[alias].last_result)

    def test_transaction_failure_preserves_all_rows_and_caches(self):
        first, second = self.record(), self.record()
        monitor = self.service.monitors[self.alias]
        monitor.last_result, monitor.previous_non_exam_result = second, first
        before = self.store.history()
        self.store.connection.execute("CREATE TRIGGER synthetic_delete_failure BEFORE DELETE ON results "
                                      "WHEN OLD.id=2 BEGIN SELECT RAISE(ABORT, 'synthetic_failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.delete_history(all=True)
        self.assertEqual(self.store.history(), before)
        self.assertIs(monitor.last_result, second)
        self.assertIs(monitor.previous_non_exam_result, first)

    def test_failed_later_batch_chunk_rolls_back_an_already_deleted_chunk(self):
        rows = [self.record() for _ in range(405)]
        ordered = sorted(row['record_id'] for row in rows)
        self.store.connection.execute("CREATE TRIGGER synthetic_chunk_failure BEFORE DELETE ON results "
                                      "WHEN OLD.record_id='" + ordered[-1] + "' "
                                      "BEGIN SELECT RAISE(ABORT, 'synthetic_failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.delete_history(record_ids=ordered)
        self.assertEqual(self.store.history_count(), 405)

    def test_deleted_screen_clears_review_eligibility_under_an_exam_card(self):
        from relay_auditor.protocol import Protocol
        from test_assessment import SimulatedClient
        alias = self.service.configure('https://relay.invalid/v1', 'synthetic', 'deepseek-flash',
                                       Protocol(wire_api='deepseek'), reference_key='synthetic-official')
        self.service.client_factory = SimulatedClient
        self.store.set_limits(500, 5000000)
        with patch('relay_auditor.controller.threading') as scheduler:
            job = self.service.submit(alias, 'assessment', seed=42)
        worker = scheduler.Thread.call_args.kwargs
        worker['target'](*worker['args'])
        monitor = self.service.monitors[alias]
        screen = monitor.last_result
        self.assertEqual(self.service._review_candidate(monitor)['job_id'], job)
        monitor.previous_non_exam_result = screen
        exam = self.record(mode='capability_exam')
        monitor.last_result = exam
        self.assertEqual(self.service._review_candidate(monitor)['job_id'], job)
        self.service.delete_history(record_ids=[screen['record_id']])
        self.assertIsNone(monitor.previous_non_exam_result)
        self.assertIs(monitor.last_result, exam)
        self.assertIsNone(self.service._review_candidate(monitor))

    def test_item_diagnostics_filter_free_text_and_validate_fixed_typed_fields(self):
        item = {'question_number': 1, 'task_kind': 'exam_code', 'template': 'stack',
                'difficulty': 3, 'seed': 8, 'source_kind': 'relay', 'correct': False,
                'score': 0, 'format_state': 'valid', 'attempts': 1, 'error_code': None,
                'grading_issue': None, 'prompt': 'synthetic-private-prompt'}
        safe = safe_snapshot({'item_results': [item]})['item_results'][0]
        self.assertEqual(safe, {key: value for key, value in item.items() if key != 'prompt'})
        unsafe = safe_snapshot({'item_results': [item | {'template': 'synthetic-private-text',
                                'correct': 1, 'score': 9, 'format_state': 'ok', 'grading_issue': 'synthetic-private-text'}]})['item_results'][0]
        for field in ('template', 'correct', 'score', 'format_state', 'grading_issue'):
            self.assertIsNone(unsafe[field])
        aggregate = {'suite_version': 'assessment-v4', 'assessment_counts': [{'correct': 3, 'attempted': 5}]}
        self.assertEqual(safe_snapshot(aggregate), aggregate)

    def test_delete_preserves_budget_events_reservations_baselines_limits_and_audit_index(self):
        self.store.set_limits(1000, 1000000)
        ticket = self.store.reserve(200)
        self.store.settle(ticket, {'total_tokens': 80})
        self.store.next_audit()
        self.store.reserve_batch(2, 100)
        self.store.put_baseline('gpt-test', 'synthetic-v1-' + 'a' * 16, [[1] * 429],
                                '2026-11-01T00:00:00+00:00', 'gpt-test')
        before = {table: self.store.connection.execute('SELECT * FROM ' + table).fetchall()
                  for table in ('daily', 'events', 'batches', 'baselines', 'limits')}
        self.record()
        self.service.delete_history(all=True)
        after = {table: self.store.connection.execute('SELECT * FROM ' + table).fetchall() for table in before}
        self.assertEqual(after, before)
        self.assertEqual(self.store.next_audit()[0], 2)

    def test_surviving_review_marks_missing_source_using_entire_database_without_rewriting_stats(self):
        source_job = uuid.uuid4().hex
        source = self.record(job_id=source_job)
        for _ in range(201):
            self.record()
        review = self.record(review_of=source_job, paired_result={'valid_pairs': 40, 'target_correct': 30})
        monitor = self.service.monitors[self.alias]
        monitor.last_result = review
        before_payload = self.store.connection.execute('SELECT data FROM results WHERE record_id=?',
                                                       (review['record_id'],)).fetchone()[0]
        self.assertFalse(self.service.snapshot()['history'][0]['review_source_deleted'])
        self.service.delete_history(record_ids=[source['record_id']])
        state = self.service.snapshot()
        self.assertTrue(state['history'][0]['review_source_deleted'])
        self.assertTrue(state['targets'][0]['last_result']['review_source_deleted'])
        self.assertEqual(state['history'][0]['paired_result'], review['paired_result'])
        self.assertEqual(self.store.connection.execute('SELECT data FROM results WHERE record_id=?',
                                                       (review['record_id'],)).fetchone()[0], before_payload)
        self.assertNotIn('review_source_deleted', monitor.last_result)

    def test_controller_holds_lock_until_storage_and_cache_deletion_complete(self):
        row = self.record()
        monitor = self.service.monitors[self.alias]
        monitor.last_result = row
        entered, release, lock_checked = threading.Event(), threading.Event(), threading.Event()
        held = []
        original = self.store.delete_history

        def blocking_delete(**options):
            entered.set()
            release.wait(2)
            return original(**options)

        def check_lock():
            self.assertTrue(entered.wait(1))
            acquired = self.service.lock.acquire(blocking=False)
            held.append(not acquired)
            if acquired:
                self.service.lock.release()
            lock_checked.set()
            release.set()

        checker = threading.Thread(target=check_lock)
        checker.start()
        with patch.object(self.store, 'delete_history', side_effect=blocking_delete):
            self.service.delete_history(record_ids=[row['record_id']])
        checker.join(2)
        self.assertTrue(lock_checked.is_set())
        self.assertEqual(held, [True])
        self.assertIsNone(monitor.last_result)

    def test_anonymous_snapshot_accepts_only_anonymous_history_fields(self):
        identifier = uuid.uuid4().hex
        safe = safe_snapshot({'record_id': identifier, 'history_count': 5, 'review_source_deleted': True,
                              'api_key': 'synthetic-secret'})
        self.assertEqual(safe, {'record_id': identifier, 'history_count': 5, 'review_source_deleted': True})
        self.assertIsNone(safe_snapshot({'record_id': 'synthetic-private-text'})['record_id'])

    def test_post_delete_uses_existing_origin_header_and_session_guards(self):
        first, second = self.record(), self.record()
        server = make_server(self.service)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'

        def post(body, **options):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            try:
                headers = {'Origin': origin, 'Content-Type': 'application/json', 'X-Relay-Request': '1'}
                headers.update(options.get('headers', {}))
                conn.request('POST', options.get('path', server.session_path + 'history_delete'),
                             json.dumps(body), headers)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        for options in ({'headers': {'Origin': 'http://untrusted.invalid'}},
                        {'headers': {'X-Relay-Request': '0'}}, {'path': '/history_delete'}):
            self.assertEqual(post({'all': True}, **options)[0], 403)
        for body in ({'record_ids': [first['record_id'], 'invalid']}, {'all': True, 'record_ids': []},
                     {'all': True, 'extra': True}):
            self.assertEqual(post(body), (400, {'ok': False, 'error': 'invalid_history_delete'}))
        self.service.busy = True
        self.assertEqual(post({'all': True}), (400, {'ok': False, 'error': 'history_busy'}))
        self.service.busy = False
        self.assertEqual(post({'record_ids': [first['record_id']]}),
                         (200, {'ok': True, 'deleted_count': 1, 'total_remaining': 1}))
        self.assertEqual(post({'all': True}), (200, {'ok': True, 'deleted_count': 1, 'total_remaining': 0}))
        self.assertNotEqual(first['record_id'], second['record_id'])


class LegacyHistoryMigrationTests(unittest.TestCase):
    def legacy_database(self, directory):
        path = Path(directory) / 'audit.sqlite'
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('CREATE TABLE results (id INTEGER PRIMARY KEY, data TEXT)')
            for identifier in (3, 9):
                connection.execute('INSERT INTO results VALUES (?,?)',
                                   (identifier, json.dumps({'schema_version': 1, 'mode': 'quality'})))
        return path

    def test_legacy_duplicate_payloads_receive_unique_persistent_ids_without_payload_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.legacy_database(directory)
            with closing(sqlite3.connect(path)) as connection:
                before = connection.execute('SELECT id,data FROM results ORDER BY id').fetchall()
            store = Store(directory)
            try:
                ids = [row['record_id'] for row in store.history()]
                self.assertEqual(len(set(ids)), 2)
                self.assertEqual(store.connection.execute('SELECT id,data FROM results ORDER BY id').fetchall(), before)
            finally:
                store.close()
            restarted = Store(directory)
            try:
                self.assertEqual([row['record_id'] for row in restarted.history()], ids)
            finally:
                restarted.close()

    def test_failed_migration_rolls_back_column_and_all_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.legacy_database(directory)
            with patch('relay_auditor.storage.uuid.uuid4', side_effect=[uuid.UUID(int=1), RuntimeError('synthetic')]):
                with self.assertRaises(RuntimeError):
                    Store(directory)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual([row[1] for row in connection.execute('PRAGMA table_info(results)')], ['id', 'data'])
                self.assertEqual(connection.execute('SELECT id FROM results ORDER BY id').fetchall(), [(3,), (9,)])
