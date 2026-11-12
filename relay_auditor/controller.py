"""Opt-in scheduler and independent screening/confirmation workflows."""
from __future__ import annotations

from dataclasses import dataclass, field, replace,asdict
from datetime import datetime, timezone
import math
import secrets
import threading
import time
import uuid
from urllib.parse import urlsplit

from . import SCHEMA_VERSION

from .protocol import Protocol, PROBE_KINDS, make_case, category, sequence_features, feature_distance,OFFICIAL_ENDPOINTS
from .statistics import permutation_audit, compare_paired
from .storage import Store, BudgetExceeded, safe_snapshot
from .transport import APIClient, Target, EndpointError
from .models import display_name as checked_name, model_choices
from .families import family_for, REFERENCE_FAMILY, usable_reference, reasoning_reference, reference_identity, reference_issue
from .planning import EXAM_MODE, exam_available, exam_plan

REFERENCE_BLOCKERS = frozenset(('authentication_failed', 'unsupported_parameters', 'reference_model_unavailable'))


def configured_reference(protocol, key, model, declared_model):
    family = family_for(declared_model)
    if family != 'unknown' and family != REFERENCE_FAMILY[protocol.wire_api]:
        raise ValueError('reference_provider_mismatch')
    return Target(OFFICIAL_ENDPOINTS[protocol.wire_api], key, model, protocol, role='reference')


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Cancelled(Exception):
    pass


@dataclass(repr=False)
class Monitor:
    target: Target = field(repr=False)
    reference: Target | None = field(default=None, repr=False)
    reference_model: str | None = None
    enabled: bool = False
    interval_seconds: float = 900
    active_only: bool = True
    last_started: float | None = None
    last_active: float | None = None
    last_result: dict | None = None
    previous_non_exam_result: dict | None = None
    anomalies: int = 0
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    display_name: str = field(default='未命名测试', repr=False)
    models: list = field(default_factory=list)
    reference_follows_model: bool = True
    target_id: str = field(default_factory=lambda:uuid.uuid4().hex)
    source_alias: str | None = None
    credential_ready: bool = True
    credentials_saved: bool = False
    reference_wire_api: str | None = None
    reference_preset: str | None = None
    reference_saved: bool = False
    reference_declared_model: str | None = None
    reference_protocol: Protocol | None = None
    reference_state: str | None = None
    reference_error: str | None = None


@dataclass(frozen=True, repr=False)
class ExamApproval:
    target_id: str
    target: Target
    reference: Target | None
    plan: dict
    limits: tuple[int, int]
    expires: float


class Service:
    def __init__(self, store: Store, *, client_factory=APIClient, clock=time.time,profiles=None):
        self.store, self.client_factory, self.clock = store, client_factory, clock
        self.epoch_id = uuid.uuid4().hex
        self.monitors = {}
        self.next_target_number = 1
        self.lock = threading.RLock()
        self.busy = False
        self.running_mode = None
        self.notification_id = 0
        self.catalog = None
        self.catalog_source = None
        self.stop_event = threading.Event()
        self.jobs={}; self.pending=[]; self.current_job=None; self.progress={}; self._latencies=[]
        self.exam_previews: dict[str, ExamApproval] = {}
        self.queued_exams: dict[str, ExamApproval] = {}
        self.local_usage = {'local_status': 'no_data', 'source_kind': 'unknown',
                            'source_attribution': 'unknown_historical_route'}
        self.profiles=profiles
        self.on_idle=None
        self.settings_status='not_configured' if profiles is None else 'ok'
        if profiles is not None:
            try:
                rows,self.next_target_number=profiles.load_state()
                for row in rows:
                    try: secret=profiles.secret(row) or {}
                    except ValueError: secret={}
                    protocol=Protocol(**row['protocol'])
                    relay_key = secret.get('relay') if row['credentials_saved'] else None
                    target=Target(row['base_url'],relay_key or 'locked-profile',row['model'],protocol)
                    reference_wire = row['reference_wire_api']
                    reference_protocol = None
                    preset_id = row.get('reference_preset')
                    reference = None
                    reference_error = None
                    if preset_id:
                        reference_protocol = Protocol(**row['reference_protocol']) if row['reference_protocol'] else None
                        if (reference_protocol and row.get('reference_saved') and secret.get('official_preset') == preset_id
                                and secret.get('official_reference')):
                            from .official import official_model, restore_reference
                            try:
                                if official_model(preset_id, row['reference_declared_model']) != row['reference_model']:
                                    raise ValueError('reference_model_mismatch')
                                reference = restore_reference(preset_id, secret['official_reference'], row['reference_model'], reference_protocol)
                            except ValueError as error:
                                reference_error = 'reference_model_retired' if str(error) == 'reference_model_retired' else 'reference_model_unavailable'
                    elif reference_wire and secret.get('reference') and secret.get('legacy_reference_wire', reference_wire) == reference_wire:
                        reference = Target(OFFICIAL_ENDPOINTS[reference_wire], secret['reference'], row['reference_model'],
                                           replace(protocol, wire_api=reference_wire), role='reference')
                    self.monitors[row['source_alias']]=Monitor(target,reference,reference_model=row['reference_model'],
                        interval_seconds=row['interval_seconds'],active_only=row['active_only'],display_name=row['display_name'],
                        models=row['models'],reference_follows_model=row['reference_follows_model'],target_id=row['target_id'],
                        source_alias=row['source_alias'],
                        credential_ready=bool(row['credentials_saved'] and secret.get('relay')),
                        credentials_saved=row['credentials_saved'],reference_wire_api=reference_wire,
                        reference_preset=preset_id, reference_saved=row['reference_saved'] or bool(secret.get('reference') and not preset_id),
                        reference_declared_model=row.get('reference_declared_model'), reference_state=row.get('reference_state'),
                        reference_protocol=reference_protocol if preset_id else None, reference_error=reference_error)
            except ValueError:
                self.monitors.clear(); self.settings_status='unavailable'

    def _persist(self,monitor,**changes):
        if self.profiles is None: return
        if self.settings_status=='unavailable': raise ValueError('profiles_unavailable')
        from dataclasses import asdict
        row={'target_id':monitor.target_id,'display_name':monitor.display_name,'base_url':monitor.target.base_url,
             'source_alias':monitor.source_alias,
             'model':monitor.target.model,'protocol':asdict(monitor.target.protocol),'reference_model':monitor.reference_model,
             'reference_wire_api':monitor.reference_wire_api,
             'reference_preset':monitor.reference_preset,'reference_saved':monitor.reference_saved,
             'reference_declared_model':monitor.reference_declared_model,'reference_state':monitor.reference_state,
             'reference_protocol':asdict(monitor.reference_protocol) if monitor.reference_protocol else None,
             'reference_follows_model':monitor.reference_follows_model,'models':monitor.models,
             'interval_seconds':monitor.interval_seconds,'active_only':monitor.active_only,'credentials_saved':monitor.credentials_saved}
        self.profiles.save(row|changes)

    def _stored_keys(self, monitor, saving=False):
        if self.profiles is None:
            if saving:
                raise ValueError('profiles_unavailable')
            return {}
        if saving or monitor.credentials_saved or monitor.reference_saved:
            return self.profiles.vault.read(monitor.target_id) or {}
        return {}

    def _persist_with_keys(self, monitor, previous, updated, **settings):
        changed = previous != updated
        if changed:
            if updated:
                self.profiles.save_secret(monitor.target_id, updated)
            else:
                self.profiles.vault.delete(monitor.target_id)
        try:
            self._persist(monitor, **settings)
        except Exception:
            if changed:
                if previous:
                    self.profiles.save_secret(monitor.target_id, previous)
                else:
                    self.profiles.vault.delete(monitor.target_id)
            raise

    def set_official_reference(self, target_id, preset_id, api_key, *, save_credentials=False):
        from .official import PRESETS, official_model, reference_target, compatible_protocols
        if type(save_credentials) is not bool:
            raise ValueError('invalid_save_credentials')
        if save_credentials and (self.profiles is None or not self.profiles.vault.available):
            raise ValueError('vault_unavailable')
        with self.lock:
            if self.busy:
                raise ValueError('busy')
            found = next(((alias, item) for alias, item in self.monitors.items() if item.target_id == target_id), None)
            if found is None:
                raise ValueError('target_not_found')
            alias, monitor = found
            relay = monitor.target
            previous_reference = monitor.reference
            previous_preset = monitor.reference_preset
            if relay.role != 'relay' or urlsplit(relay.base_url).hostname.rstrip('.') in {
                urlsplit(preset.base_url).hostname for preset in PRESETS.values()
            }:
                raise ValueError('official_direct')
        model = official_model(preset_id, relay.model)
        preset = PRESETS[preset_id]
        reference = reference_target(preset_id, relay, api_key, model)
        if not compatible_protocols(preset_id, relay.protocol, reference.protocol, model):
            raise ValueError('reference_settings_mismatch')
        state = 'reference_pending'
        if preset.discovery_path is not None:
            available = self.client_factory(reference).list_models()
            if model not in available:
                raise ValueError('reference_model_unavailable')
            state = 'reference_matched'
        with self.lock:
            if (self.busy or self.monitors.get(alias) is not monitor or monitor.target is not relay
                or monitor.reference is not previous_reference or monitor.reference_preset != previous_preset):
                raise ValueError('reference_changed')
            previous = self._stored_keys(monitor, save_credentials)
            updated = {name: key for name, key in previous.items() if name == 'relay'}
            if save_credentials:
                updated.update(official_reference=api_key, official_preset=preset_id)
            self._persist_with_keys(
                monitor, previous, updated, reference_preset=preset_id, reference_saved=save_credentials,
                reference_model=model, reference_declared_model=relay.model, reference_state=state,
                reference_protocol=asdict(reference.protocol), reference_follows_model=False,
                reference_wire_api=reference.protocol.wire_api,
            )
            monitor.reference = reference
            monitor.reference_model = model
            monitor.reference_preset = preset_id
            monitor.reference_saved = save_credentials
            monitor.reference_declared_model = relay.model
            monitor.reference_protocol = reference.protocol
            monitor.reference_state = state
            monitor.reference_error = None
            monitor.reference_wire_api = reference.protocol.wire_api
            monitor.reference_follows_model = False
            monitor.last_result, monitor.anomalies = None, 0
            self._disable_target(monitor)
            return {'reference_state': state, 'reference_model': model}

    def target_for(self,alias):
        with self.lock:
            monitor=self.monitors[alias]
            if not monitor.credential_ready: raise ValueError('credential_required')
            return monitor.target

    def credentials(self,alias,api_key,*,reference_key=None,save_credentials=False):
        with self.lock:
            if self.busy: raise ValueError('busy')
            monitor=self.monitors[alias]
            if not api_key:
                if not monitor.credential_ready: raise ValueError('credential_required')
                api_key = monitor.target.api_key
            target=replace(monitor.target,api_key=api_key)
            reference = monitor.reference
            reference_wire = monitor.reference_wire_api
            if reference_key:
                if target.role != 'relay': raise ValueError('official_direct')
                if monitor.reference_preset:
                    raise ValueError('reference_use_panel')
                reference = configured_reference(target.protocol, reference_key, monitor.reference_model, target.model)
                reference_wire = reference.protocol.wire_api
            if type(save_credentials) is not bool: raise ValueError('invalid_save_credentials')
            previous = self._stored_keys(monitor, save_credentials)
            updated = {name: key for name, key in previous.items() if name != 'relay'}
            if save_credentials:
                updated['relay'] = api_key
            if reference_key:
                updated.pop('reference', None)
                updated.pop('legacy_reference_wire', None)
                if save_credentials:
                    updated.update(reference=reference_key, legacy_reference_wire=reference_wire)
            reference_saved = bool(updated.get('official_reference') if monitor.reference_preset else updated.get('reference'))
            self._persist_with_keys(monitor, previous, updated, credentials_saved=save_credentials,
                                    reference_wire_api=reference_wire, reference_saved=reference_saved)
            if target != monitor.target or reference != monitor.reference:
                monitor.last_result, monitor.anomalies = None, 0
            monitor.target,monitor.reference,monitor.credential_ready,monitor.credentials_saved=target,reference,True,save_credentials
            monitor.reference_wire_api = reference_wire
            monitor.reference_saved = reference_saved
            self._disable_target(monitor)

    def configure(self, base_url, api_key, model, protocol=None, *, reference_key=None, reference_model=None,
                  display_name=None, models=None,save_credentials=False):
        if type(save_credentials) is not bool: raise ValueError('invalid_save_credentials')
        name = checked_name(display_name)
        protocol = protocol or Protocol()
        target = Target(base_url, api_key, model, protocol)
        if reference_key and target.role != 'relay': raise ValueError('official_direct')
        reference = configured_reference(protocol, reference_key, reference_model or model, model) if reference_key else None
        with self.lock:
            if self.busy:
                raise ValueError('busy')
            alias = f'relay-{self.next_target_number}'
            from .protocol import model_name
            expected_model = model_name(reference_model or model)
            monitor=Monitor(target, reference, reference_model=expected_model, display_name=name,
                            models=model_choices([model]+(models or [])), reference_follows_model=not bool(reference_model),
                            source_alias=alias,
                            credentials_saved=save_credentials, reference_wire_api=protocol.wire_api,
                            reference_saved=bool(save_credentials and reference))
            if save_credentials:
                if self.profiles is None: raise ValueError('profiles_unavailable')
                saved = {'relay': api_key}
                if reference_key:
                    saved.update(reference=reference_key, legacy_reference_wire=protocol.wire_api)
                self.profiles.save_secret(monitor.target_id, saved)
            try: self._persist(monitor)
            except Exception:
                if save_credentials: self.profiles.vault.delete(monitor.target_id)
                raise
            self.monitors[alias]=monitor
            self.next_target_number+=1
        return alias

    def update_target(self, alias, *, display_name, model, reasoning_effort=None, wire_api=None, max_output_tokens=None):
        name = checked_name(display_name)
        with self.lock:
            if self.busy:
                raise ValueError('busy')
            monitor = self.monitors[alias]
            protocol = replace(monitor.target.protocol, reasoning_effort=reasoning_effort or None,
                               wire_api=wire_api if wire_api is not None else monitor.target.protocol.wire_api,
                               max_output_tokens=max_output_tokens if max_output_tokens is not None else monitor.target.protocol.max_output_tokens)
            target = replace(monitor.target, model=model, protocol=protocol)
            reference = monitor.reference
            expected_reference = model if monitor.reference_follows_model else monitor.reference_model
            if reference and not monitor.reference_preset:
                reference = replace(reference, model=expected_reference,
                                    protocol=replace(protocol, wire_api=reference.protocol.wire_api))
            changed = target.model != monitor.target.model or protocol != monitor.target.protocol
            from dataclasses import asdict
            self._persist(monitor,display_name=name,model=model,protocol=asdict(protocol),reference_model=expected_reference,
                          models=model_choices(monitor.models+[model]))
            monitor.target, monitor.reference, monitor.display_name = target, reference, name
            monitor.reference_model = expected_reference
            monitor.models = model_choices(monitor.models+[model])
            if changed:
                monitor.enabled = False
                monitor.cancel.set()
                monitor.last_result, monitor.anomalies = None, 0

    def ui_snapshot(self):
        from .reports import explain
        with self.lock:
            snapshot = self.snapshot()
            return snapshot | {
                'report_cards': self.report_cards(),
                'history_reports': [explain(row) for row in snapshot['history']],
                'official_presets': self.official_presets(),
                'display_names':{a:m.display_name for a,m in self.monitors.items()},
                'model_choices':{a:m.models for a,m in self.monitors.items()},
                'catalog_models':{row['source_alias']:self.catalog.get(row['source_alias']).models
                                  for row in self.catalog.summary()} if self.catalog else {},
                'catalog_reasoning':{row['source_alias']:self.catalog.get(row['source_alias']).reasoning_effort
                                    for row in self.catalog.summary()} if self.catalog else {},
                'vault_available':bool(self.profiles and self.profiles.vault.available),'settings_status':self.settings_status}

    @staticmethod
    def official_presets():
        from .official import PRESETS
        return [{'id': key, 'label': preset.label} for key, preset in PRESETS.items()]

    def _disable_target(self, monitor):
        monitor.enabled = False
        monitor.cancel.set()
        for job_id in self.pending:
            if self.jobs[job_id]['target_id'] == monitor.target_id:
                self.jobs[job_id]['state'] = 'cancelled'
                self.queued_exams.pop(job_id, None)
        self.exam_previews = {key: approval for key, approval in self.exam_previews.items()
                              if approval.target_id != monitor.target_id}
        self.pending = [job_id for job_id in self.pending if self.jobs[job_id]['state'] == 'queued']

    def delete_target(self, target_id):
        with self.lock:
            monitor = next((m for m in self.monitors.values() if m.target_id == target_id), None)
            if monitor is None:
                raise ValueError('unknown_target')
            if self.busy and self.progress.get('target_id') == target_id:
                raise ValueError('target_running')
            try:
                if self.profiles is not None:
                    self.profiles.remove(target_id, credentials_saved=monitor.credentials_saved or monitor.reference_saved)
            except ValueError as error:
                if str(error) == 'target_delete_rollback_failed':
                    monitor.target = replace(monitor.target, api_key='locked-profile')
                    monitor.credential_ready = False
                    monitor.reference = None
                    self._disable_target(monitor)
                raise
            self._disable_target(monitor)
            del self.monitors[monitor.source_alias]

    def delete_history(self, record_ids=None, *, all=None):
        with self.lock:
            ids = self.store.history_delete_ids(record_ids, all=all)
            if self.busy or self.pending:
                raise ValueError('history_busy')
            result = self.store.delete_history(record_ids=record_ids, all=all)
            for monitor in self.monitors.values():
                for attribute in ('last_result', 'previous_non_exam_result'):
                    cached = getattr(monitor, attribute)
                    if cached is not None and (ids is None or cached.get('record_id') in ids):
                        setattr(monitor, attribute, None)
            return result

    @staticmethod
    def _history_result_view(result, job_keys):
        if result is None:
            return None
        value = dict(result)
        if value.get('review_of'):
            value['review_source_deleted'] = (value.get('target_id'), value['review_of']) not in job_keys
        return value

    def control(self, alias, *, enabled=None, interval_seconds=None, active_only=None):
        with self.lock:
            monitor = self.monitors[alias]
            if enabled is not None and type(enabled) is not bool:
                raise ValueError('invalid_enabled')
            if interval_seconds is not None and (type(interval_seconds) not in (float, int)
                    or not math.isfinite(interval_seconds) or interval_seconds <= 0):
                raise ValueError('invalid_interval')
            if active_only is not None and type(active_only) is not bool:
                raise ValueError('invalid_activity_setting')
            if enabled and not monitor.credential_ready: raise ValueError('credential_required')
            self._persist(monitor,interval_seconds=interval_seconds if interval_seconds is not None else monitor.interval_seconds,
                          active_only=active_only if active_only is not None else monitor.active_only)
            if enabled is False:
                self._disable_target(monitor)
            elif enabled is True:
                monitor.enabled = True
            if interval_seconds is not None:
                monitor.interval_seconds = interval_seconds
            if active_only is not None:
                monitor.active_only = active_only

    def mark_active(self, alias, timestamp=None):
        with self.lock:
            self.monitors[alias].last_active = self.clock() if timestamp is None else timestamp

    def due(self, alias, now=None):
        monitor = self.monitors[alias]
        now = self.clock() if now is None else now
        active = monitor.last_active is not None and now - monitor.last_active <= 1800
        return (monitor.enabled and (not monitor.active_only or active)
                and (monitor.last_started is None or now - monitor.last_started >= monitor.interval_seconds))

    def tick(self):
        with self.lock:
            if self.busy:
                return
            due = next((a for a in self.monitors if self.due(a)), None)
            if due:
                mode = 'assessment' if self.monitors[due].target.role == 'official_api' or family_for(self.monitors[due].target.model) != 'unknown' else 'screen'
                self.submit(due, mode, automatic=True)

    def start(self):
        def loop():
            while not self.stop_event.wait(1):
                self.tick()
        threading.Thread(target=loop, daemon=True, name='relay-schedule').start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            for monitor in self.monitors.values():
                monitor.cancel.set()
            for job_id in self.pending: self.jobs[job_id]['state']='cancelled'
            self.pending.clear()
            self.exam_previews.clear()
            self.queued_exams.clear()

    def _begin(self, alias, mode, automatic=False):
        with self.lock:
            if self.busy:
                if automatic:
                    return None
                raise ValueError('busy')
            monitor = self.monitors[alias]
            if not monitor.credential_ready: raise ValueError('credential_required')
            if automatic and not self.due(alias):
                return None
            monitor.cancel.clear()
            if mode != EXAM_MODE:
                monitor.last_started = self.clock()
            self.busy, self.running_mode = True, mode
            self.progress={'source_alias':alias,'target_id':monitor.target_id,'mode':mode,'completed':0,'total':0}
            self._latencies=[]
            return monitor

    def _review_candidate(self, monitor):
        from .assessment import VERSION
        result = monitor.last_result or {}
        if result.get('mode') == EXAM_MODE:
            result = monitor.previous_non_exam_result or {}
        pair = result.get('paired_result') or {}
        reference = usable_reference(monitor)
        if (reference and result.get('job_id') and result.get('mode') == 'assessment'
                and result.get('suite_version') == VERSION and result.get('status') == 'ok'
                and not result.get('review_of') and result.get('task_count') == 10
                and pair.get('valid_pairs') == 10 and (pair.get('accuracy_loss') or 0) >= .10
                and result.get('model') == monitor.target.model
                and result.get('protocol_id') == monitor.target.protocol.identity
                and result.get('reference_model') == reference.model
                and result.get('reference_protocol_id') == reference.protocol.identity
                and result.get('reference_preset') == monitor.reference_preset):
            return result
        return None

    def _exam_status(self, monitor, approval):
        if monitor is None or monitor.target_id != approval.target_id or monitor.target is not approval.target:
            return 'exam_changed'
        if approval.plan['comparison'] == 'paired' and usable_reference(monitor) is not approval.reference:
            return 'exam_changed'
        budget = self.store.budget()
        if (budget['request_limit'], budget['token_limit']) != approval.limits:
            return 'exam_changed'
        return exam_plan(monitor, approval.plan['sample_count'], approval.plan['comparison'], budget)['status']

    def _confirm_exam(self, monitor, samples, plan_id):
        approval = self.exam_previews.pop(plan_id, None) if isinstance(plan_id, str) else None
        if (approval is None or approval.expires <= time.monotonic()
                or (samples is not None and samples != approval.plan['sample_count'])):
            raise ValueError('exam_changed')
        status = self._exam_status(monitor, approval)
        if status != 'ok':
            raise ValueError(status)
        return approval

    def submit(self, alias, mode, samples=None, *, automatic=False,seed=None,expected_requests=None,review_of=None,exam_plan_id=None):
        from .planning import MODES, assessment_plan
        with self.lock:
            if seed is not None and (type(seed) is not int or not 0<=seed<2**31): raise ValueError('invalid_seed')
            if self.stop_event.is_set(): raise ValueError('stopped')
            if mode not in MODES:
                raise ValueError('invalid_mode')
            if samples is not None and (type(samples) is not int or not 1<=samples<=200): raise ValueError('invalid_samples')
            monitor=self.monitors[alias]
            if not monitor.credential_ready: raise ValueError('credential_required')
            approval = None
            if mode == EXAM_MODE:
                if automatic or seed is not None or review_of is not None:
                    raise ValueError('exam_changed')
                if any(job['mode'] == EXAM_MODE and job['target_id'] == monitor.target_id
                       and job['state'] in ('queued', 'running', 'cancelling') for job in self.jobs.values()):
                    raise ValueError('busy')
                approval = self._confirm_exam(monitor, samples, exam_plan_id)
                samples = approval.plan['sample_count']
            if automatic and (self.busy or self.pending or not self.due(alias)): return False
            if review_of is not None:
                candidate = self._review_candidate(monitor)
                if (automatic or mode != 'assessment' or not candidate or candidate['job_id'] != review_of
                        or samples is None or samples < 40 or seed is not None
                        or expected_requests != assessment_plan(monitor, samples)['required_requests']):
                    raise ValueError('assessment_changed')
                # Draw a fresh seed with a disjoint question-seed range.
                limit = 2**31
                offset = candidate['task_count'] + secrets.randbelow(limit - samples - candidate['task_count'] + 1)
                seed = (candidate['task_seed'] + offset) % limit
            if mode == 'assessment':
                for job_id, job in self.jobs.items():
                    if job['mode'] == mode and job['source_alias'] == alias and job['state'] in ('queued', 'running', 'cancelling'):
                        if review_of is not None and job.get('review_of') != review_of:
                            raise ValueError('assessment_changed')
                        return job_id
                if expected_requests is not None and expected_requests != assessment_plan(monitor, samples)['required_requests']:
                    raise ValueError('assessment_changed')
            if len(self.pending)>=50: raise ValueError('queue_full')
            job_id=uuid.uuid4().hex
            self.jobs[job_id]={'job_id':job_id,'source_alias':alias,'target_id':monitor.target_id,'model':monitor.target.model,
                               'protocol_id':monitor.target.protocol.identity,'mode':mode,'sample_count':samples,'task_seed':seed,
                               'state':'queued','automatic':automatic}
            if review_of is not None:
                self.jobs[job_id]['review_of'] = review_of
            if approval is not None:
                self.queued_exams[job_id] = approval
            self.pending.append(job_id)
            self._drain()
            return job_id

    def _drain(self):
        if self.busy or self.stop_event.is_set(): return
        while self.pending:
            job_id=self.pending.pop(0); job=self.jobs[job_id]; alias=job['source_alias']; monitor=self.monitors.get(alias)
            approval = self.queued_exams.pop(job_id, None)
            if approval is not None and job['state'] == 'queued':
                status = self._exam_status(monitor, approval)
                if status != 'ok':
                    job['state'] = status
                    continue
            if (job['state']!='queued' or monitor is None or not monitor.credential_ready or job['target_id']!=monitor.target_id
                    or job['model']!=monitor.target.model or job['protocol_id']!=monitor.target.protocol.identity):
                job['state']='cancelled'; continue
            if job.get('review_of') and (self._review_candidate(monitor) or {}).get('job_id') != job['review_of']:
                job['state'] = 'cancelled'
                continue
            monitor=self._begin(alias,job['mode'])
            self.current_job=job_id; job['state']='running'
            self.progress['job_id']=job_id
            args = (alias, monitor, job['mode'], job['sample_count'], job['task_seed'], not job['automatic'])
            if approval is not None:
                args += (approval.plan,)
            threading.Thread(target=self._run, args=args, daemon=True, name='relay-detection').start()
            break
        # Bounded completed metadata; active jobs are never discarded.
        if len(self.jobs)>200:
            for key in list(self.jobs):
                if len(self.jobs)<=200: break
                if self.jobs[key]['state'] not in ('queued','running','cancelling'): self.jobs.pop(key)

    def cancel(self,job_id=None):
        with self.lock:
            if job_id is None:
                job_id=self.current_job
                if job_id is None: return
            if job_id is not None and job_id not in self.jobs: raise ValueError('unknown_job')
            for key,job in self.jobs.items():
                if job_id is not None and key!=job_id: continue
                if job['state']=='queued':
                    job['state']='cancelled'
                    self.queued_exams.pop(key, None)
                elif key==self.current_job and self.busy:
                    job['state']='cancelling'; self.monitors[job['source_alias']].cancel.set()
            self.pending=[key for key in self.pending if self.jobs[key]['state']=='queued']

    def set_progress(self,total):
        with self.lock: self.progress['total']=total

    def set_retry_progress(self, retry):
        with self.lock:
            if retry is None:
                self.progress.pop('retry', None)
            else:
                self.progress['retry'] = retry

    def set_exam_progress(self, sides):
        with self.lock:
            self.progress['exam_progress'] = [
                {key: side[key] for key in ('source_kind', 'completed', 'sample_count')} for side in sides
            ]

    def wait_for_retry(self, monitor, seconds):
        if monitor.cancel.wait(seconds) or self.stop_event.is_set():
            raise Cancelled()

    def estimate(self,alias,mode,samples=None,prices=None,*,comparison=None):
        from .planning import estimate, assessment_plan
        with self.lock:
            m=self.monitors[alias]
            if mode == EXAM_MODE:
                budget = self.store.budget()
                plan = exam_plan(m, samples, comparison, budget)
                if plan['status'] != 'ok':
                    return plan
                now = time.monotonic()
                self.exam_previews = {key: approval for key, approval in self.exam_previews.items()
                                      if approval.expires > now}
                if len(self.exam_previews) >= 64:
                    self.exam_previews.pop(next(iter(self.exam_previews)))
                plan_id = uuid.uuid4().hex
                reference = usable_reference(m) if plan['comparison'] == 'paired' else None
                self.exam_previews[plan_id] = ExamApproval(m.target_id, m.target, reference, plan,
                                                           (budget['request_limit'], budget['token_limit']), now + 600)
                return {**plan, 'exam_plan_id': plan_id}
            if mode == 'assessment':
                plan = assessment_plan(m, samples)
                if not self.store.available(plan['required_requests'], plan['estimated_tokens']):
                    plan['status'] = 'budget_exhausted'
                return plan
            reference = reasoning_reference(m) if mode == 'reasoning' else usable_reference(m)
            return estimate(mode,samples,m.target.protocol,reference is not None,prices)

    def run(self, alias, mode, samples=None,*,seed=None,exam_plan_id=None):
        if seed is not None and (type(seed) is not int or not 0<=seed<2**31): raise ValueError('invalid_seed')
        if mode == EXAM_MODE:
            with self.lock:
                if self.stop_event.is_set() or seed is not None:
                    raise ValueError('exam_changed')
                approval = self._confirm_exam(self.monitors[alias], samples, exam_plan_id)
                monitor = self._begin(alias, mode)
            return self._run(alias, monitor, mode, approval.plan['sample_count'], approved_exam=approval.plan)
        return self._run(alias, self._begin(alias, mode), mode, samples,seed)

    def _call(self, monitor, case, *, reference=False, batch=None):
        if monitor.cancel.is_set() or self.stop_event.is_set():
            raise Cancelled()
        if self.profiles and not self.profiles.has_target(monitor.target_id):
            with self.lock:
                self._disable_target(self.monitors.get(monitor.source_alias, monitor))
            raise Cancelled()
        owner = self.monitors.get(monitor.source_alias, monitor)
        target = usable_reference(monitor) if reference else monitor.target
        if target is None or (reference and owner.reference_error):
            raise EndpointError('reference_required')
        ticket = self.store.reserve(len(case.prompt.encode()) + target.protocol.max_output_tokens + 256, target.role, batch=batch)
        started=time.monotonic()
        try:
            result = self.client_factory(target).complete(case)
        except EndpointError as error:
            self.store.settle(ticket, None)
            if reference and monitor.reference_preset and str(error) in REFERENCE_BLOCKERS:
                with self.lock:
                    owner.reference_error = str(error)
            raise
        except KeyboardInterrupt:
            self.store.settle(ticket,None)
            raise
        except Exception:
            self.store.settle(ticket, None)
            raise EndpointError('local_error') from None
        finally:
            with self.lock:
                self.progress['completed']=self.progress.get('completed',0)+1
                self.progress['total']=max(self.progress.get('total',0),self.progress['completed'])
                self._latencies.append(time.monotonic()-started)
        self.store.settle(ticket, result.usage)
        if reference and owner.reference_state == 'reference_pending' and result.complete:
            with self.lock:
                owner.reference_state = 'reference_matched'
        return result

    def _identity(self, monitor, feature):
        if feature is None:
            return {'identity_state': 'invalid_probe'}
        identity = reference_identity(monitor)
        baseline = self.store.baseline(monitor.target.model, identity, monitor.reference_model) if identity else None
        if not baseline:
            return {'identity_state': 'baseline_missing'}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(baseline['completed_at'])).total_seconds()
        rows = baseline['baseline_features']
        if not 0<=age<=7*86400:
            return {'identity_state': 'baseline_stale', 'baseline_age_seconds': age, 'provenance_level':baseline.get('provenance_level','historical_official_reference')}
        center = [sum(x) / len(rows) for x in zip(*rows)]
        distances = sorted(feature_distance(row, center) for row in rows)
        threshold = max(0.08, distances[-1] * 1.25)
        distance = feature_distance(feature, center)
        state = 'screening_deviation' if distance > threshold else 'screening_consistent'
        if len(rows) < 12:
            state = 'insufficient_data'
        return {'identity_state': state, 'identity_distance': distance, 'identity_threshold': threshold,
                'baseline_samples': len(rows), 'baseline_id': baseline['baseline_id'], 'baseline_age_seconds': age, 'provenance_level':baseline.get('provenance_level','historical_official_reference')}

    def _screen(self, monitor):
        result = {'response_count': 0, 'network_failures': 0, 'capability_attempted': 2,
                  'capability_correct': 0, 'capability_valid': 0, 'invalid_responses': 0,
                  'capability_completed': 0, 'identity_state': 'insufficient_data'}
        seed = secrets.randbelow(2**31)
        for kind in ('sequence', 'trace', 'logic'):
            case = make_case(kind, seed)
            try:
                response = self._call(monitor, case)
            except EndpointError as error:
                result['network_failures'] += 1
                result['error_code'] = str(error)
                continue
            result['response_count'] += 1
            if kind == 'sequence':
                result.update(self._identity(monitor, sequence_features(response.text) if response.complete else None))
            else:
                result['capability_completed'] += 1
                grade = case.grade(response.text) if response.complete else {'valid': False, 'correct': False}
                result['capability_valid'] += grade['valid']
                result['capability_correct'] += grade['correct']
                result['invalid_responses'] += not grade['valid']
        result['accuracy'] = (result['capability_correct'] / result['capability_completed']
                              if result['capability_completed'] else None)
        result['capability_state'] = ('unavailable' if not result['capability_valid'] else
                                      'incomplete_comparison' if result['capability_valid'] < 2 else
                                      'screening_failure' if result['capability_correct'] < result['capability_valid']
                                      else 'observed_answers_correct')
        result['detected_anomaly'] = (result['identity_state'] == 'screening_deviation'
                                      or result['capability_state'] == 'screening_failure')
        return result

    def _baseline(self, monitor, samples):
        if usable_reference(monitor) is None:
            raise EndpointError('reference_required')
        features = []
        failures = 0
        for i in range(samples):
            try:
                response = self._call(monitor, make_case('sequence', i), reference=True)
                feature = sequence_features(response.text) if response.complete else None
            except EndpointError:
                feature = None
            if feature:
                features.append(feature)
            else:
                failures += 1
            if monitor.reference_error:
                break
        if monitor.reference_error:
            raise EndpointError(monitor.reference_error)
        data = self.store.put_baseline(monitor.target.model, reference_identity(monitor), features, stamp(),
                                       monitor.reference_model) if features else None
        return {'baseline_id': data['baseline_id'] if data else None, 'baseline_samples': len(features),
                'sample_count': samples, 'invalid_responses': failures,
                'identity_state': 'insufficient_data' if len(features) < 12 else 'screening_consistent',
                'provenance_level': 'historical_official_reference'}

    def _audit(self, monitor, samples, capability, progress):
        if usable_reference(monitor) is None:
            raise EndpointError('reference_required')
        count = samples * 2 * (1 if capability else len(PROBE_KINDS))
        # Full-batch preflight: no unexpected partial 500-request audit.
        batch = self.store.reserve_batch(count, monitor.target.protocol.max_output_tokens + 1024)
        reference, suspect = {k: [] for k in PROBE_KINDS}, {k: [] for k in PROBE_KINDS}
        pairs, failures, invalid = [], 0, 0
        kinds = ('trace',) if capability else PROBE_KINDS
        try:
            index, alpha = self.store.next_audit()
            progress.update(audit_index=index, alpha=alpha, sample_count=count,
                            response_count=0, network_failures=0, invalid_responses=0,
                            identity_state='insufficient_data')
            for i in range(samples):
                for kind in kinds:
                    case = make_case(('trace' if i % 2 else 'logic') if capability else kind, index * 100000 + i)
                    values = {}
                    for is_reference in ((True, False) if i % 2 == 0 else (False, True)):
                        if is_reference and monitor.reference_error:
                            continue
                        try:
                            response = self._call(monitor, case, reference=is_reference, batch=batch)
                            progress['response_count'] += 1
                            if capability:
                                grade = case.grade(response.text)
                                values[is_reference] = grade['correct'] if grade['valid'] and response.complete else None
                                invalid += values[is_reference] is None
                            else:
                                value = category(kind, response.text) if response.complete else 'OTHER'
                                (reference if is_reference else suspect)[kind].append(value)
                                invalid += value == 'OTHER'
                        except EndpointError:
                            failures += 1
                            values[is_reference] = None
                        progress.update(network_failures=failures, invalid_responses=invalid)
                    if capability:
                        pairs.append((values.get(True), values.get(False)))
        finally:
            self.store.release_batch(batch)
        result = {'audit_index': index, 'alpha': alpha, 'sample_count': count,
                  'network_failures': failures, 'invalid_responses': invalid}
        if capability:
            comparison = compare_paired(pairs, alpha=alpha)
            comparison['reference_correct'] = sum(ref for ref, actual in pairs if ref is not None and actual is not None)
            comparison['target_correct'] = sum(actual for ref, actual in pairs if ref is not None and actual is not None)
            result.update(paired_result=comparison, capability_state=comparison['status'],
                          detected_anomaly=comparison['status'] == 'degraded')
            if comparison['valid_pairs']:
                result['provenance_level'] = 'same_time_official_reference'
        elif failures or samples < 20:
            result['identity_state'] = 'insufficient_data'
        else:
            permutations = min(100000, max(9999, math.ceil(10 / alpha)))
            comparison = permutation_audit(reference, suspect, alpha=alpha, permutations=permutations)
            result.update(comparison)
            result['provenance_level'] = 'same_time_official_reference'
            result['identity_state'] = (comparison['status'] if comparison['status'] != 'ok' else
                                        'behavior_deviation' if comparison['significant'] else 'no_detected_deviation')
            result['detected_anomaly'] = comparison['significant']
        return result

    def _run(self, alias, monitor, mode, samples,seed=None,recover=True,approved_exam=None):
        reference = None
        if mode == 'reasoning':
            reference = reasoning_reference(monitor)
        elif mode in ('assessment', 'quality_audit', 'baseline', 'identity_audit', 'capability_audit', 'screen'):
            reference = usable_reference(monitor)
        elif mode == EXAM_MODE and approved_exam and approved_exam['comparison'] == 'paired':
            reference = usable_reference(monitor)
        reference_model = reference.model if reference else None
        if mode == 'screen' and not monitor.reference_preset:
            reference_model = monitor.reference_model
        result = {'schema_version': 2, 'snapshot_type': 'assessment', 'epoch_id': self.epoch_id,'target_id':monitor.target_id,
                  'source_alias': alias, 'source_kind': monitor.target.role, 'mode': mode, 'status': 'ok',
                  'model': monitor.target.model, 'protocol_id': monitor.target.protocol.identity,
                  'reference_model': reference_model,
                  'reference_preset': monitor.reference_preset if reference else None,
                  'reference_protocol_id': reference.protocol.identity if reference else None,
                  'comparison_conditions':asdict(monitor.target.protocol),
                  'validation_state': 'experimental', 'evaluated_at': stamp()}
        if reference:
            result['reference_comparison_conditions'] = asdict(reference.protocol)
        try:
            count = (12 if mode == 'baseline' else 40 if mode == 'capability_audit' else 50) if samples is None else samples
            if type(count) is not int or not 1 <= count <= 200:
                raise ValueError('invalid_samples')
            if monitor.target.role == 'official_api' and mode in ('baseline', 'identity_audit', 'capability_audit', 'quality_audit'):
                raise EndpointError('official_direct')
            if mode == 'assessment':
                from .assessment import run_assessment
                run_assessment(self, monitor, samples, result, seed=seed, recover=recover)
                if result.get('detected_anomaly') and not monitor.cancel.is_set():
                    self.notification_id += 1
            elif mode == EXAM_MODE:
                from .exam import run_exam
                run_exam(self, monitor, approved_exam, result, seed=secrets.randbelow(2**31))
            elif mode in ('quality','quality_audit','context','reasoning'):
                from .quality import run_quality
                result.update(run_quality(self,monitor,mode,samples,result,seed=seed))
                if result.get('detected_anomaly') and not monitor.cancel.is_set(): self.notification_id+=1
            elif mode == 'screen':
                self.set_progress(3)
                result['suite_version']='fingerprint-v1'
                result.update(self._screen(monitor))
                monitor.anomalies = monitor.anomalies + 1 if result.get('detected_anomaly') else 0
                if monitor.anomalies >= 2 and monitor.enabled and not monitor.cancel.is_set():
                    # Additional independent responses, capped at 4 rounds = 12 requests.
                    sustained = False
                    for _ in range(4):
                        repeated = self._screen(monitor)
                        sustained = sustained or repeated.get('detected_anomaly', False)
                    result['detected_anomaly'] = sustained
                    if sustained and not monitor.cancel.is_set():
                        self.notification_id += 1
            elif mode == 'baseline':
                self.set_progress(count)
                result.update(self._baseline(monitor, count))
            elif mode in ('identity_audit', 'capability_audit'):
                self.set_progress(count*(2 if mode=='capability_audit' else 10))
                result.update(self._audit(monitor, count, mode == 'capability_audit', result))
                if result.get('detected_anomaly') and not monitor.cancel.is_set():
                    self.notification_id += 1
            else:
                raise ValueError('invalid_mode')
        except Cancelled:
            result['status'] = 'cancelled'
        except KeyboardInterrupt:
            result['status']='cancelled'; monitor.cancel.set()
            raise
        except BudgetExceeded:
            result['status'] = 'budget_exhausted'
        except EndpointError as error:
            result.update(status='unavailable', error_code=str(error))
        except Exception:
            result.update(status='unavailable', error_code='local_error')
        finally:
            if reference and monitor.reference_error:
                result['reference_error'] = monitor.reference_error
            if self.current_job:
                result['job_id'] = self.current_job
                review_of = self.jobs[self.current_job].get('review_of')
                if review_of:
                    result['review_of'] = review_of
            if self._latencies:
                result['latency_mean']=sum(self._latencies)/len(self._latencies)
                result['latency_p95']=sorted(self._latencies)[math.ceil(len(self._latencies)*.95)-1]
            result['completed_at'] = stamp()
            result['notification_id'] = self.notification_id
            from .reports import upgrade
            safe = upgrade(result)
            if mode != EXAM_MODE:
                from .reports import trend
                safe['dimensions']['stability']=trend([r for r in self.store.history(200) if r.get('target_id')==monitor.target_id]+[safe])
            try:
                safe['record_id'] = self.store.record(safe)
            except Exception:
                safe.update(status='unavailable', error_code='local_error')
            finally:
                with self.lock:
                    if mode == EXAM_MODE and (monitor.last_result or {}).get('mode') != EXAM_MODE:
                        monitor.previous_non_exam_result = monitor.last_result
                    monitor.last_result = safe
                    self.busy, self.running_mode = False, None
                    if self.current_job:
                        self.jobs[self.current_job]['state']='finished' if safe['status']=='ok' else safe['status']
                    self.current_job=None
                    self._drain()
                    if not self.busy and self.on_idle: self.on_idle()
        return safe

    def report_cards(self):
        from .reports import explain
        return {alias: explain(m.last_result) for alias, m in self.monitors.items() if m.last_result}

    def usage_snapshot(self):
        with self.lock:
            return safe_snapshot({
                'schema_version': SCHEMA_VERSION, 'snapshot_type': 'usage',
                'epoch_id': self.epoch_id, 'generated_at': stamp(),
                'usage': {**self.store.usage(), **self.local_usage},
            })

    def snapshot(self):
        from .planning import assessment_plan, support
        from .reports import upgrade, comparisons
        with self.lock:
            history_job_keys = self.store.history_job_keys()
            reviews = {alias: self._review_candidate(m) for alias, m in self.monitors.items()}
            targets = [{'source_alias': alias, 'model': m.target.model, 'protocol_id': m.target.protocol.identity,
                        'source_kind':m.target.role, 'model_family':family_for(m.target.model),
                        'assessment_plan':assessment_plan(m),
                        'exam_available':exam_available(m),
                        'wire_api':m.target.protocol.wire_api,
                        'target_id':m.target_id,'credential_ready':m.credential_ready,
                        'review_available':reviews[alias] is not None,
                        'review_job_id':reviews[alias]['job_id'] if reviews[alias] else None,
                        'reference_preset':m.reference_preset,'reference_model':m.reference_model,
                        'reference_saved':m.reference_saved,'reference_error':reference_issue(m),
                        'reasoning_effort':m.target.protocol.reasoning_effort,
                        'max_output_tokens':m.target.protocol.max_output_tokens,
                        'enabled': m.enabled, 'interval_seconds': m.interval_seconds, 'active_only': m.active_only,
                        'status': 'credential_required' if not m.credential_ready else 'disabled' if not m.enabled else 'running' if self.busy else
                                  'waiting_for_activity' if m.active_only and not self.due(alias) and m.last_active is None else 'idle',
                        'last_result': self._history_result_view(m.last_result, history_job_keys),
                        'stale': m.last_result is None or not m.enabled or
                                 self.clock() - (m.last_started or 0) > max(m.interval_seconds * 2, 1800)}
                       for alias, m in self.monitors.items()]
            support_rows = []
            for monitor in self.monitors.values():
                binding = reference_identity(monitor)
                baseline = self.store.baseline(monitor.target.model, binding, monitor.reference_model) if binding else None
                support_rows.append(support(monitor, baseline))
            history = [self._history_result_view(upgrade(row), history_job_keys) for row in self.store.history(200)]
            return safe_snapshot({'schema_version': 2, 'snapshot_type': 'assessment', 'epoch_id': self.epoch_id,
                              'generated_at': stamp(), 'targets': targets, 'busy': self.busy,
                              'running_mode': self.running_mode, 'notification_id': self.notification_id,
                              'catalog': {'catalog_source': self.catalog_source,
                                          'catalog_id': self.catalog.catalog_id if self.catalog else None,
                                          'providers': self.catalog.summary() if self.catalog else []},
                              'budget': self.store.budget(), 'usage': {**self.store.usage(), **self.local_usage},
                              'history':history,'history_count':self.store.history_count(),'comparisons':comparisons(history),
                              'jobs':list(self.jobs.values()),'progress':self.progress,
                              'support':support_rows})
