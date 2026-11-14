"""Keyless study estimates; no saved accounts, budgets or credentials are opened."""
from .calibration import validate
from .exam_registry import get_exam_spec,is_exam_suite
from .planning import ASSESSMENT_PROMPT_BYTES, estimate
from .protocol import Protocol


def preview(manifest, *, request_limit=None, token_limit=None):
    """Describe proposed frozen inputs without creating or authorizing a study.

    Limits describe one day's hypothetical capacity before any existing spend.
    Token reservations use the production planning bounds, not provider billing.
    """
    validate(manifest)
    for value, maximum in ((request_limit, 100000), (token_limit, 10**10)):
        if value is not None and (type(value) is not int or not 1 <= value <= maximum):
            raise ValueError('invalid_budget')
    protocol = Protocol(**manifest['protocol'])
    spec = get_exam_spec(manifest['family'],manifest['suite_version']) if is_exam_suite(manifest['suite_selection']) else None
    per_trial = []
    for scenario in manifest['scenarios']:
        context = scenario == 'context_truncated'
        retries = 0 if context else manifest['retry_policy']['max_retry_requests_per_trial']
        requests = manifest['samples'] * 2
        if context:
            context_plan = estimate('context', manifest['samples'], protocol, True)
            per_call = context_plan['estimated_tokens'] // context_plan['required_requests']
        else:
            prompt_bound = spec.max_prompt_bytes if spec else ASSESSMENT_PROMPT_BYTES
            per_call = prompt_bound + protocol.max_output_tokens + 256
        per_trial.append({
            'scenario': scenario,
            'suite_version': manifest['specialist_context_suite'] if context else manifest['suite_version'],
            'planned_requests': requests, 'planned_retry_requests': retries,
            'max_requests': requests + retries, 'estimated_tokens': (requests + retries) * per_call,
            'per_call': per_call,
        })

    def stage(phase, start, stop):
        trials = stop - start
        return {'phase': phase, 'date_basis': manifest['validation_date_basis'],
                'start_trial': start, 'stop_trial': stop, 'trials_per_scenario': trials,
                'trials': trials * len(per_trial),
                **{field: trials * sum(row[field] for row in per_trial)
                   for field in ('planned_requests', 'planned_retry_requests', 'max_requests', 'estimated_tokens')}}

    stages = [stage('pilot', 0, manifest['pilot_trials'])]
    stages.extend(stage('validation', block['start_trial'], block['stop_trial'])
                  for block in manifest['validation_blocks'])
    budget_rows = []
    for row in per_trial:
        request_gap = None if request_limit is None else max(0, row['max_requests'] - request_limit)
        token_gap = None if token_limit is None else max(0, row['estimated_tokens'] - token_limit)
        fits = False if request_gap or token_gap else None if request_gap is None or token_gap is None else True
        budget_rows.append({'scenario': row['scenario'], 'request_gap': request_gap,
                            'token_gap': token_gap, 'fits_supplied_limits': fits})
    state = ('insufficient' if any(row['fits_supplied_limits'] is False for row in budget_rows)
             else 'unknown' if request_limit is None or token_limit is None else 'fits_supplied_limits')
    suggested_limits = {
        'request_limit': max(row['max_requests'] for row in per_trial),
        'token_limit': max(row['estimated_tokens'] for row in per_trial),
        'basis': 'one_complete_trial_including_retries',
        'applied': False, 'user_confirmation_required': True,
    }
    notice = {'unknown': 'default_budget_requires_confirmation',
              'insufficient': 'supplied_limits_insufficient',
              'fits_supplied_limits': 'within_proposed_limits_existing_usage_unchecked'}[state]
    return {
        'schema_version': 1, 'action': 'offline_calibration_plan', 'frozen': False,
        'collection_authorized': False, 'real_api_requests': 0, 'validation_state': 'experimental',
        'access_state': 'not_checked', 'model_visibility': 'not_checked',
        'model_version_state': 'requested_ids_unverified',
        'family': manifest['family'], 'primary_model': manifest['primary_model'],
        'alternative_model': manifest['alternative_model'], 'protocol': dict(manifest['protocol']),
        'suite_selection': manifest['suite_selection'], 'suite_version': manifest['suite_version'],
        'scope': manifest['scope'], 'samples': manifest['samples'], 'seed': manifest['seed'],
        'audit_index': manifest['audit_index'], 'alpha': manifest['alpha'],
        'pilot_trials_per_scenario': manifest['pilot_trials'], 'validation_trials_per_scenario': manifest['trials'],
        'token_estimate_basis': 'conservative_reservation_not_billing', 'estimated_cost': None, 'currency': 'unknown',
        'validation_requires_later_distinct_dates': True,
        'per_trial': per_trial, 'stages': stages,
        'total': {field: sum(row[field] for row in stages)
                  for field in ('trials', 'planned_requests', 'planned_retry_requests', 'max_requests', 'estimated_tokens')},
        'budget': {'state': state, 'request_limit': request_limit, 'token_limit': token_limit,
                   'suggested_limits': suggested_limits, 'notice': notice,
                   'scope': 'single_trial_daily_capacity', 'existing_daily_usage_checked': False,
                   'per_trial': budget_rows},
    }
