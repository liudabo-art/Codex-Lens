"""Reproducible offline exercises for decision rules, using invented outcomes."""
import json
import random

from .assessment import VERSION, assessment_comparison, run_assessment
from .controller import Monitor
from .protocol import Protocol
from .reports import trend
from .statistics import spending_alpha
from .transport import Completion, EndpointError, Target

SAMPLE_SIZES = (40, 80, 120, 200)
SCENARIOS = {
    'healthy': (.05, .05),
    'minor_loss': (.10, .05),
    'weak_substitution': (.25, .05),
    'reasoning_changed': (.15, .05),
    # Mixtures of the healthy and weak-substitution outcome distributions.
    'mixed_10': (.07, .05),
    'mixed_30': (.11, .05),
    'mixed_50': (.15, .05),
    'context_truncated': (.50, .05),
}
REFERENCE_ACCURACY = .90
# Reference missing, relay missing when correct, relay missing when incorrect.
MISSINGNESS = {
    'none': (0., 0., 0.),
    'symmetric': (.005, .005, .005),
    'relay_only': (0., .03, .03),
    'failure_biased': (.005, .005, .15),
}


def _paired_matrix(rng, trials, alpha):
    for scenario, (regression, improvement) in SCENARIOS.items():
        for missingness, (ref_missing, correct_missing, incorrect_missing) in MISSINGNESS.items():
            rows = [dict(scenario=scenario, missingness=missingness, pairs=n,
                         verdicts={}, valid_pairs=0, decision_ready=0, lower_sum=0., upper_sum=0.)
                    for n in SAMPLE_SIZES]
            for _ in range(trials):
                pairs = []
                for _ in range(SAMPLE_SIZES[-1]):
                    outcome = rng.random()
                    reference = outcome < REFERENCE_ACCURACY
                    target = regression <= outcome < REFERENCE_ACCURACY + improvement
                    target_missing = correct_missing if target else incorrect_missing
                    pairs.append((None if rng.random() < ref_missing else reference,
                                  None if rng.random() < target_missing else target))
                for row in rows:
                    n = row['pairs']
                    observed = pairs[:n]
                    ready = all(ref is not None and target is not None for ref, target in observed)
                    result = assessment_comparison(observed, n, alpha=alpha if ready else None)
                    row['valid_pairs'] += result['valid_pairs']
                    row['decision_ready'] += ready
                    lower, upper = result.get('loss_bounds', (result['accuracy_loss'],) * 2)
                    row['lower_sum'] += lower
                    row['upper_sum'] += upper
                    verdict = result['status']
                    row['verdicts'][verdict] = row['verdicts'].get(verdict, 0) + 1
            for row in rows:
                attempts = row['pairs'] * trials
                bounds = [row.pop('lower_sum') / trials, row.pop('upper_sum') / trials]
                yield {**row, 'paired_attempts': attempts, 'hypothetical_requests_per_trial': row['pairs'] * 2,
                       'valid_pair_fraction': row['valid_pairs'] / attempts,
                       'decision_ready_fraction': row['decision_ready'] / trials,
                       'mean_missingness_loss_bounds': bounds}


def _wrong(value):
    if type(value) is int:
        return value + 1
    if isinstance(value, str):
        return 'B' if value == 'A' else 'A'
    if isinstance(value, list):
        return [_wrong(value[0]), *value[1:]] if value else [0]
    if isinstance(value, dict) and value:
        key = next(iter(value))
        return {**value, key: _wrong(value[key])}
    raise ValueError('unsupported_synthetic_answer')


class _SyntheticRound:
    """In-memory request boundary for the actual assessment scorer."""
    def __init__(self, correct, *, failed=False):
        self.correct, self.failed, self.calls = correct, failed, 0
        self.store = self
        self.progress = {'completed': 0}

    def reserve_batch(self, requests, per_call):
        return None

    def release_batch(self, batch):
        pass

    def set_progress(self, total):
        pass

    def _call(self, monitor, case, *, reference=False, batch=None):
        if reference:
            raise AssertionError('unexpected reference request')
        self.calls += 1
        self.progress['completed'] = self.calls
        if self.failed and self.calls == 10:
            raise EndpointError('network_error')
        answer = case.expected if self.calls <= self.correct else _wrong(case.expected)
        return Completion(json.dumps({'answer': answer}))


def _standalone_histories(seed):
    target = Target('https://synthetic.invalid/v1', 'synthetic-only', 'gpt-synthetic', Protocol())
    monitor = Monitor(target=target, target_id='0' * 32)
    for name, scores in (('stable', (10, 9, 10, 9)), ('sustained_decline', (10, 10, 8, 9)),
                         ('one_failed_round', (10, 10, 8, 9))):
        records = []
        for index, correct in enumerate(scores):
            result = dict(target_id=monitor.target_id, status='ok', mode='assessment', model=target.model,
                          protocol_id=target.protocol.identity, evaluated_at=f'2000-01-01T00:00:0{index}+00:00')
            run_assessment(_SyntheticRound(correct, failed=name == 'one_failed_round' and index == 3),
                           monitor, 10, result, seed=seed + 1000 * index)
            records.append(result)
        rounds = [dict(attempted=row['capability_attempted'], valid=row['capability_valid'],
                       correct=row['capability_correct'], state=row['capability_state'],
                       reference_requests=sum(side['attempted'] for side in row['assessment_counts']
                                              if side['source_kind'] == 'reference')) for row in records]
        yield name, {'rounds': rounds, 'trend': trend(records)}


def simulate(*, trials=100, seed=20261109, audit_index=1):
    if type(trials) is not int or not 1 <= trials <= 1000 or type(seed) is not int or not 0 <= seed < 10**9:
        raise ValueError('invalid_simulation')
    if type(audit_index) is not int or not 1 <= audit_index <= 100000:
        raise ValueError('invalid_simulation')
    alpha = spending_alpha(audit_index)
    return {'schema_version': 1, 'evidence': 'synthetic_simulation', 'real_api_requests': 0,
            'suite_version': VERSION, 'seed': seed, 'trials_per_cell': trials, 'audit_index': audit_index,
            'alpha': alpha, 'reference_accuracy': REFERENCE_ACCURACY,
            'scenario_parameters': {name: {'regression_probability': r, 'improvement_probability': i}
                                    for name, (r, i) in SCENARIOS.items()},
            'missingness_parameters': {name: {'reference': ref, 'relay_when_correct': correct,
                                             'relay_when_incorrect': incorrect}
                                       for name, (ref, correct, incorrect) in MISSINGNESS.items()},
            'paired': list(_paired_matrix(random.Random(seed), trials, alpha)),
            'no_reference': dict(_standalone_histories(seed))}
