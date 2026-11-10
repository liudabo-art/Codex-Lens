"""Finite-sample, fixed-batch comparisons. No model-identity certification."""
from collections import Counter
import math
import random

MINIMUM_PAIRED_SAMPLES = 40

def jsd(left, right):
    ltotal, rtotal = sum(left.values()), sum(right.values())
    if not ltotal or not rtotal:
        return 0.0
    result = 0.0
    for key in left.keys() | right.keys():
        p, q = left.get(key, 0) / ltotal, right.get(key, 0) / rtotal
        m = (p + q) / 2
        if p:
            result += 0.5 * p * math.log2(p / m)
        if q:
            result += 0.5 * q * math.log2(q / m)
    return max(0.0, result)


def spending_alpha(index):
    if type(index) is not int or index < 1:
        raise ValueError('invalid_audit_index')
    return 0.01 / (index * (index + 1))


def permutation_audit(reference, suspect, *, permutations=9999, seed=20261102, alpha=0.005):
    result = {'status': 'insufficient_data', 'statistic': None, 'p_value': None,
              'alpha': alpha, 'significant': False, 'permutations': permutations}
    if (not reference or set(reference) != set(suspect)
            or any(not reference[k] or not suspect[k] for k in reference)):
        return result
    if not 0 < alpha < 1 or type(permutations) is not int or not 1 <= permutations <= 100000:
        raise ValueError('invalid_test_configuration')
    keys = sorted(reference)
    statistic = sum(jsd(Counter(reference[k]), Counter(suspect[k])) for k in keys) / len(keys)
    result['statistic'] = statistic
    if 1 / (permutations + 1) > alpha:
        result['status'] = 'insufficient_resolution'
        return result
    if statistic <= 1e-15:
        return {**result, 'status': 'ok', 'p_value': 1.0}
    rng = random.Random(seed)
    groups = [(list(reference[k]) + list(suspect[k]), len(reference[k])) for k in keys]
    extreme = 0
    for _ in range(permutations):
        score = 0.0
        for pool, split in groups:
            rng.shuffle(pool)
            score += jsd(Counter(pool[:split]), Counter(pool[split:]))
        extreme += score / len(keys) >= statistic - 1e-15
    p = (extreme + 1) / (permutations + 1)
    return {**result, 'status': 'ok', 'p_value': p, 'significant': p <= alpha}


def paired_p_value(regressions, improvements):
    discordant = regressions + improvements
    return sum(math.comb(discordant, k) for k in range(regressions, discordant + 1)) / 2**discordant


def compare_paired(pairs, *, alpha=0.005, minimum_effect=0.10, minimum_pairs=MINIMUM_PAIRED_SAMPLES):
    pairs = list(pairs)
    valid = [(a, b) for a, b in pairs if type(a) is bool and type(b) is bool]
    n = len(valid)
    regressions = sum(a and not b for a, b in valid)
    improvements = sum(not a and b for a, b in valid)
    p = paired_p_value(regressions, improvements)
    loss = (regressions - improvements) / n if n else None
    if n != len(pairs):
        status = 'incomplete_comparison'
    elif n < minimum_pairs:
        status = 'insufficient_data'
    elif loss >= minimum_effect and p <= alpha:
        status = 'degraded'
    elif loss >= minimum_effect:
        status = 'inconclusive'
    else:
        status = 'no_detected_degradation'
    return {'status': status, 'attempted_pairs': len(pairs), 'valid_pairs': n,
            'regressions': regressions, 'improvements': improvements,
            'accuracy_loss': loss, 'p_value': p if n else None, 'alpha': alpha,
            'baseline_accuracy': sum(a for a, _ in valid) / n if n else None,
            'current_accuracy': sum(b for _, b in valid) / n if n else None}
