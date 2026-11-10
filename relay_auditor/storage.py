"""Private aggregate storage. Never persists endpoint configuration or raw answers."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
import uuid

SAFE_KEYS = set('''schema_version snapshot_type epoch_id generated_at targets history budget usage reasoning_effort
target_id job_id review_of review_available suite_version evidence_level dimensions quality behavior reliability stability interval latency_mean latency_p95
wire_api context_results task_seed task_count comparison_conditions reference_comparison_conditions max_output_tokens temperature stream adapter_version
recommendation accuracy_change trend comparisons credential_ready vault_available settings_status jobs progress completed total
estimated_cost currency input_price output_price context_characters reasoning_comparison effort reference_accuracy
support model_family can_connect basic_evaluation matched_reference calibrated tools_structured state
source_alias source_kind coverage status enabled interval_seconds active_only busy last_result
model reference_model protocol_id identity_state capability_state validation_state evaluated_at
mode error_code sample_count response_count valid_responses invalid_responses network_failures
capability_correct capability_valid capability_attempted capability_completed accuracy identity_distance identity_threshold
baseline_samples baseline_id baseline_age_seconds stale cancelled notification_id
requests estimated_tokens reported_tokens unknown_usage_requests request_limit token_limit day
audit_index alpha statistic p_value significant permutations paired_result planned_pairs attempted_pairs valid_pairs loss_bounds
regressions improvements accuracy_loss baseline_accuracy current_accuracy
input_tokens output_tokens cached_input_tokens reasoning_output_tokens total_tokens
probe_tokens reference_tokens probe_requests reference_requests unknown_usage baseline_features
observed_local_tokens observed_local_responses source_attribution local_status last_usage_at
cost_is_estimate detected_anomaly caveat finite_probe_counts other_count required_requests target_requests
running_mode warning_count baseline_count completed_at provenance_level
official_login relay official_api unknown probe reference relay_providers record_count invalid_records groups
held_requests held_tokens
catalog catalog_id catalog_source providers current_selected can_detect
assessment_plan reference_state assessment_tasks assessment_counts task_kind difficulty attempted valid correct response_issues behavior_samples agreements
reference_correct target_correct direct_probe_tokens direct_probe_requests
reference_preset reference_saved reference_error reference_protocol_id
retry retry_requests max_retry_requests retry_question retry_attempt failure_source
'''.split())
SAFE_WORDS = set('''usage assessment relay unknown baseline_missing baseline_stale none minimal low medium high xhigh max
responses chat anthropic gemini text-v1
quality quality_audit context reasoning constraints code repair structured tool_args quality-v1 quality-v2 context-v1 fingerprint-v1 legacy-v1
legacy_unverified matched_official_comparison historical_reference basic_observation user_history not_comparable historical_decline_signal
review_reference collect_more_evidence credential_required saved queued cancelling finished unsupported_genuine_calibration
not_configured comparable incomplete native_openai native_anthropic native_gemini unrecognized unknown_cost USD
screening_consistent screening_deviation invalid_probe no_reference experimental unavailable
screen screen_repeat baseline identity_audit capability_audit ok cancelled budget_exhausted
reference_required insufficient_data insufficient_resolution incomplete_comparison degraded
no_detected_degradation inconclusive observed_answers_correct screening_failure
behavior_deviation no_detected_deviation protocol_mismatch local_error network_error
authentication_failed rate_limited unsupported_parameters http_error invalid_response remote_error
redirect_blocked response_too_large invalid_synthetic_case disabled idle waiting_for_activity
running paused_budget stopped no_data provider_match_unverified unknown_historical_route
local_usage_only same_time_official_reference historical_official_reference
request_evidence_required
official_login official_api configuration_only cc_switch codexplusplus
assessment-v1 assessment-v2 assessment-v3 reference_matched reference_mismatch reference_missing official_direct identity_uncalibrated not_tested
reference_pending reference_key_required reference_unavailable reference_model_unavailable reference_model_retired
deepseek gpt claude qwen glm kimi minimax grok mistral llama document digit dice color weekday coin
output_limit stream_interrupted empty_answer response_filtered incomplete_output answer_format recovered_format
code_branch repair_edges constraints_multi
'''.split())
STRING_FIELDS = {'model', 'reference_model'}


def safe_snapshot(value):
    """Drop unknown fields and free-form strings, including remote error text."""
    def clean(item, key=''):
        if isinstance(item, dict):
            return {k: clean(v, k) for k, v in item.items() if k in SAFE_KEYS}
        if isinstance(item, list):
            return [clean(v, key) for v in item[:1000]]
        if item is None or type(item) is bool:
            return item
        if type(item) in (int, float):
            return item if math.isfinite(item) else None
        if isinstance(item, str):
            if key in ('source_kind', 'failure_source') and item == 'reference':
                return item
            if key == 'reference_preset':
                from .official import PRESETS
                return item if item in PRESETS else None
            if key in STRING_FIELDS:
                from .protocol import MODEL_PATTERN
                return item if MODEL_PATTERN.fullmatch(item) else None
            if item in SAFE_WORDS:
                return item
            if key in ('generated_at', 'evaluated_at', 'completed_at', 'last_usage_at', 'day'):
                return item if re.fullmatch(r'[0-9T:.+Z-]{10,40}', item) else None
            if key in ('epoch_id', 'baseline_id', 'catalog_id', 'target_id','job_id','review_of','plan_id'):
                return item if re.fullmatch(r'[a-f0-9-]{32,36}', item) else None
            if key == 'source_alias':
                return item if re.fullmatch(r'(?:relay|catalog)-[0-9]+', item) else None
            if key in ('protocol_id', 'reference_protocol_id'):
                return item if re.fullmatch(r'synthetic-v1-[a-f0-9]{16}', item) else None
        return None
    return clean(value)


def checked_path(value):
    raw = os.fspath(value)
    if raw.startswith(('\\\\', '//')) or '://' in raw:
        raise ValueError('local_path_required')
    path = Path(os.path.abspath(raw))
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError('network_path_blocked')
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (os.name == 'nt' and getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('linked_path_blocked')
        if part == path and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError('hardlinked_output_blocked')
    return path


class BudgetExceeded(Exception):
    pass


class Store:
    def __init__(self, directory):
        self.directory = checked_path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = checked_path(self.directory / 'audit.sqlite')
        for suffix in ('-journal', '-wal', '-shm'):
            checked_path(str(self.path) + suffix)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.execute('PRAGMA journal_mode=DELETE')
        self.connection.execute('CREATE TABLE IF NOT EXISTS limits (id INTEGER PRIMARY KEY, requests INTEGER, tokens INTEGER)')
        self.connection.execute('INSERT OR IGNORE INTO limits VALUES (1,100,100000)')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS daily
            (day TEXT PRIMARY KEY, requests INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0,
             reported INTEGER DEFAULT 0, unknown INTEGER DEFAULT 0, audit_index INTEGER DEFAULT 0)''')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS events
            (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, role TEXT, reservation INTEGER,
             settled INTEGER DEFAULT 0, usage TEXT)''')
        self.connection.execute('CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, data TEXT)')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS batches
            (id TEXT PRIMARY KEY, day TEXT, requests INTEGER, tokens INTEGER, per_call INTEGER, expires REAL)''')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS baselines
            (id TEXT PRIMARY KEY, model TEXT, protocol TEXT, data TEXT)''')

    def close(self):
        with self.lock:
            self.connection.close()

    @staticmethod
    def day():
        return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    def _daily(self):
        day = self.day()
        self.connection.execute('INSERT OR IGNORE INTO daily(day) VALUES (?)', (day,))
        return day

    def set_limits(self, requests, tokens):
        if type(requests) is not int or not 1 <= requests <= 100000 or type(tokens) is not int or not 1 <= tokens <= 10**10:
            raise ValueError('invalid_budget')
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                held = self._held(self.day())
                used = self.budget()
                if held[0] and (requests < used['requests'] + held[0] or tokens < used['estimated_tokens'] + held[1]):
                    raise ValueError('batch_budget_is_reserved')
                self.connection.execute('UPDATE limits SET requests=?,tokens=? WHERE id=1', (requests, tokens))
                self.connection.execute('COMMIT')
            except Exception:
                self.connection.execute('ROLLBACK')
                raise

    def _held(self, day):
        self.connection.execute('DELETE FROM batches WHERE expires<?', (time.time(),))
        return self.connection.execute('SELECT COALESCE(SUM(requests),0),COALESCE(SUM(tokens),0) FROM batches WHERE day=?', (day,)).fetchone()

    def budget(self):
        with self.lock:
            day = self._daily()
            requests, tokens, reported, unknown, _ = self.connection.execute(
                'SELECT requests,tokens,reported,unknown,audit_index FROM daily WHERE day=?', (day,)).fetchone()
            limit, token_limit = self.connection.execute('SELECT requests,tokens FROM limits WHERE id=1').fetchone()
            held_requests, held_tokens = self._held(day)
            return {'day': day, 'requests': requests, 'estimated_tokens': tokens, 'reported_tokens': reported,
                    'unknown_usage_requests': unknown, 'request_limit': limit, 'token_limit': token_limit,
                    'cost_is_estimate': True, 'held_requests': held_requests, 'held_tokens': held_tokens}

    def available(self, requests, tokens):
        value = self.budget()
        return (value['requests'] + value['held_requests'] + requests <= value['request_limit']
                and value['estimated_tokens'] + value['held_tokens'] + tokens <= value['token_limit'])

    def reserve_batch(self, requests, per_call):
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                if not self.available(requests, requests * per_call):
                    raise BudgetExceeded()
                ticket = uuid.uuid4().hex
                self.connection.execute('INSERT INTO batches VALUES (?,?,?,?,?,?)',
                                        (ticket, self.day(), requests, requests*per_call, per_call, time.time()+300))
                self.connection.execute('COMMIT')
                return ticket
            except Exception:
                self.connection.execute('ROLLBACK')
                raise

    def release_batch(self, ticket):
        with self.lock:
            self.connection.execute('DELETE FROM batches WHERE id=?', (ticket,))

    def reserve(self, estimate, role='relay', *, batch=None):
        if type(estimate) is not int or estimate < 1 or role not in ('relay', 'reference', 'official_api'):
            raise ValueError('invalid_reservation')
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                day = self._daily()
                used = self.budget()
                if batch:
                    row = self.connection.execute('SELECT day,requests,per_call FROM batches WHERE id=?', (batch,)).fetchone()
                    if not row or row[0] != day or row[1] < 1 or estimate > row[2]:
                        raise BudgetExceeded()
                    self.connection.execute('UPDATE batches SET requests=requests-1,tokens=tokens-?,expires=? WHERE id=?',
                                            (row[2], time.time()+300, batch))
                elif used['requests'] + used['held_requests'] >= used['request_limit'] or used['estimated_tokens'] + used['held_tokens'] + estimate > used['token_limit']:
                    raise BudgetExceeded()
                self.connection.execute('UPDATE daily SET requests=requests+1,tokens=tokens+?,unknown=unknown+1 WHERE day=?', (estimate, day))
                cursor = self.connection.execute('INSERT INTO events(day,role,reservation) VALUES (?,?,?)', (day, role, estimate))
                self.connection.execute('COMMIT')
                return cursor.lastrowid
            except Exception:
                self.connection.execute('ROLLBACK')
                raise

    def settle(self, ticket, usage):
        with self.lock:
            row = self.connection.execute('SELECT day,reservation,settled FROM events WHERE id=?', (ticket,)).fetchone()
            if not row or row[2]:
                return
            day, reserved, _ = row
            safe = safe_snapshot(usage) if usage else None
            total = safe.get('total_tokens') if safe else None
            if type(total) is not int or total < 0:
                self.connection.execute('UPDATE events SET settled=1 WHERE id=?', (ticket,))
                return
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                self.connection.execute('UPDATE daily SET tokens=tokens+?,reported=reported+?,unknown=unknown-1 WHERE day=?',
                                        (total-reserved, total, day))
                self.connection.execute('UPDATE events SET settled=1,usage=? WHERE id=?', (json.dumps(safe), ticket))
                self.connection.execute('COMMIT')
            except Exception:
                self.connection.execute('ROLLBACK')
                raise

    def usage(self):
        with self.lock:
            rows = self.connection.execute('SELECT role,usage FROM events').fetchall()
        result = {'probe_tokens': 0, 'reference_tokens': 0, 'probe_requests': 0,
                  'reference_requests': 0, 'direct_probe_tokens': 0, 'direct_probe_requests': 0, 'unknown_usage': 0}
        for role, data in rows:
            prefix = {'reference': 'reference', 'official_api': 'direct_probe'}.get(role, 'probe')
            result[prefix + '_requests'] += 1
            if data:
                result[prefix + '_tokens'] += json.loads(data).get('total_tokens', 0)
            else:
                result['unknown_usage'] += 1
        return result

    def next_audit(self):
        from .statistics import spending_alpha
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                day = self._daily()
                self.connection.execute('UPDATE daily SET audit_index=audit_index+1 WHERE day=?', (day,))
                index = self.connection.execute('SELECT audit_index FROM daily WHERE day=?', (day,)).fetchone()[0]
                self.connection.execute('COMMIT')
            except Exception:
                self.connection.execute('ROLLBACK')
                raise
        return index, spending_alpha(index)

    def record(self, data):
        payload = json.dumps(safe_snapshot(data), ensure_ascii=False, allow_nan=False)
        with self.lock:
            return self.connection.execute('INSERT INTO results(data) VALUES (?)', (payload,)).lastrowid

    def history(self, limit=50):
        with self.lock:
            rows = self.connection.execute('SELECT data FROM results ORDER BY id DESC LIMIT ?', (min(limit, 200),)).fetchall()
        return [safe_snapshot(json.loads(row[0])) for row in rows]

    def put_baseline(self, model, protocol, features, captured_at, reference_model,*,provenance_level='historical_official_reference'):
        from .protocol import model_name
        model_name(model)
        if not re.fullmatch(r'synthetic-v1-[a-f0-9]{16}', protocol) or not features:
            raise ValueError('invalid_baseline')
        if any(len(row) != 429 or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in row) for row in features):
            raise ValueError('invalid_baseline')
        model_name(reference_model)
        data = {'baseline_id': uuid.uuid4().hex, 'baseline_features': features, 'reference_model': reference_model,
                'completed_at': captured_at, 'validation_state': 'experimental','provenance_level':provenance_level}
        with self.lock:
            self.connection.execute('INSERT INTO baselines VALUES (?,?,?,?)',
                                    (data['baseline_id'], model, protocol, json.dumps(data)))
        return data

    def baseline(self, model, protocol, reference_model):
        with self.lock:
            rows = self.connection.execute('SELECT data FROM baselines WHERE model=? AND protocol=? ORDER BY rowid DESC',
                                           (model, protocol)).fetchall()
        return next((value for row in rows if (value := json.loads(row[0])).get('reference_model') == reference_model), None)
