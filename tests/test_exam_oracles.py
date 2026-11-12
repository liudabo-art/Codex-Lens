"""Independent solvers read published synthetic inputs, never case.expected as input."""
import ast
from bisect import bisect_left
from collections import Counter, defaultdict
from itertools import groupby
import json
import random
import re
import unittest

from relay_auditor import exam_generators as generators
from relay_auditor.exam import (EXAM_FAMILIES, exam_cases, _dependency, _slice_repair,
                                _tier_repair, _join, _policy, _nested, _tool_plan)


def shortest(data):
    def paths(node, cost):
        if node == data['goal']:
            return [cost]
        return [total for source, target, weight in data['edges'] if source == node
                for total in paths(target, cost + weight)]
    return min(paths(data['start'], 0))


def schedule(data):
    pending = {name: (duration, parents) for name, duration, parents in data['tasks']}
    running, finished = {}, {}
    clock = 0
    while pending or running:
        done = [name for name, end in running.items() if end == clock]
        for name in done:
            finished[name] = running.pop(name)
        ready = [name for name, (_, parents) in pending.items() if all(p in finished for p in parents)]
        for name in ready:
            duration, _ = pending.pop(name)
            running[name] = clock + duration
        clock += 1
    return {'finish': finished, 'makespan': max(finished.values())}


def registers(data):
    pair = [data['initial']['a'], data['initial']['b']]
    for name, operation, amount in data['instructions']:
        target = 'ab'.index(name)
        if operation == 'swap':
            pair.reverse()
        elif operation == 'mix':
            pair[target] = pair[1 - target] * 2 - amount
        else:
            pair[target] += amount
    return dict(zip('ab', pair))


def machine(data):
    history = [data['initial']]
    for event in data['events']:
        history.append(data['transitions'][history[-1]][event])
    return {'state': history[-1], 'visits': {state: history[1:].count(state) for state in data['transitions']}}


def dedup(data):
    return {'option': next(key for key, value in data['choices'].items() if value == 'not out or out[-1] != x'),
            'output': [key for key, _ in groupby(data['values'])]}


def insertion(data):
    return {'option': next(key for key, value in data['choices'].items() if value == 'values[mid] < target'),
            'indices': [bisect_left(data['values'], target) for target in data['queries']]}


def ledger(data):
    unique = {row[0]: row for row in data['entries'] if row[3] == 'posted'}
    return {'balances': {name: initial + sum(row[2] for row in unique.values() if row[1] == name)
                         for name, initial in data['initial'].items()}, 'ids': sorted(unique)}


def interval(data):
    by_time = {row[0] for row in data['records'] if data['start'] <= row[1] < data['end']}
    by_team = {row[0] for row in data['records'] if row[2] in data['teams']}
    selected = by_time & by_team
    return {'ids': [row[0] for row in data['records'] if row[0] in selected],
            'amount': sum(row[3] for row in data['records'] if row[0] in selected)}


def grouped(data):
    buckets = defaultdict(list)
    for group, value in data['rows']:
        buckets[group].append(value)
    return {'groups': [{'key': key, 'values': sorted(buckets[key]), 'count': len(buckets[key])}
                       for key in sorted(buckets)]}


def sparse(data):
    dense = [[0] * data['width'] for _ in range(data['height'])]
    for row, column, value in data['entries']:
        dense[row][column] = value
    return {'columns': [{'column': column, 'cells': [
        {'row': row, 'value': value} for row, value in enumerate(values) if value]}
        for column, values in enumerate(zip(*dense))]}


ORACLES = {generators.shortest_path: shortest, generators.schedule: schedule,
           generators.registers: registers, generators.state_machine: machine,
           generators.dedup_repair: dedup, generators.insertion_repair: insertion,
           generators.ledger: ledger, generators.interval_records: interval,
           generators.grouped_shape: grouped, generators.sparse_shape: sparse}


def after(text, marker):
    return text.split(marker, 1)[1]


def first_json(text, marker):
    return json.JSONDecoder().raw_decode(after(text, marker))[0]


class ExamOracleTests(unittest.TestCase):
    def test_legacy_family_generators_match_input_derived_solvers(self):
        covered = set()
        for family in EXAM_FAMILIES:
            for seed in (0, 42):
                for case, level in exam_cases(family, 120, seed):
                    prompt, variant = case.prompt, case.variant
                    if variant in ('constraints', 'constraints_multi'):
                        multi = variant == 'constraints_multi'
                        marker = 'value]:\n' if multi else 'Return that sorted list.\n'
                        items = first_json(prompt, marker)
                        if not multi:
                            items = [[row['id'], row['weight'], 0, row['value']] for row in items]
                        cap = int(re.search(r'total weight <= (\d+)', prompt)[1])
                        if multi:
                            cost_cap = int(re.search(r'total cost <= (\d+)', prompt)[1])
                            needs, required = re.search(r'Selecting (\w) requires selecting (\w)', prompt).groups()
                            excluded = re.search(r'Do not select both (\w) and (\w)', prompt).groups()
                        else:
                            excluded = re.search(r'Items (\w) and (\w)', prompt).groups()
                        feasible = []
                        for mask in range(1, 1 << len(items)):
                            selected = [item for index, item in enumerate(items) if mask & (1 << index)]
                            ids = [row[0] for row in selected]
                            weight, cost, value = (sum(row[index] for row in selected) for index in (1, 2, 3))
                            if len(ids) > 3 or weight > cap or set(excluded) <= set(ids):
                                continue
                            if multi and (cost > cost_cap or (needs in ids and required not in ids)):
                                continue
                            feasible.append(((-value, cost, weight, ids) if multi else (-value, weight, ids)))
                        independent = sorted(feasible)[0][-1]
                    elif variant in ('code', 'code_branch'):
                        values = ast.literal_eval(re.search(r'^values\s*=\s*(.+)$', prompt, re.M)[1])
                        total = int(re.search(r'^total\s*=\s*(-?\d+)', prompt, re.M)[1])
                        if variant == 'code':
                            modulus = int(re.search(r'\(i\+v\)%(\d+)', prompt)[1])
                            for index, value in enumerate(values):
                                total = (total * 2 - value if (index + value) % modulus == 0
                                         else total + value * (index + 1))
                            independent = total
                        else:
                            lower = int(re.search(r'value < (-?\d+)', prompt)[1])
                            modulus = int(re.search(r'\(total \+ value\) % (\d+)', prompt)[1])
                            skipped = hits = 0
                            for index, value in enumerate(values):
                                if value < lower:
                                    total -= index
                                    skipped += 1
                                elif (total + value) % modulus == 0:
                                    total += (index + 1) * value
                                    hits += 1
                                elif total % 2:
                                    total -= value
                                else:
                                    total += index + value
                            independent = {'total': total, 'skipped': skipped, 'hits': hits}
                    elif variant == 'stack':
                        moves = ast.literal_eval(re.search(r'^moves = (.+)$', prompt, re.M)[1])
                        total = int(re.search(r'^total = (\d+)$', prompt, re.M)[1])
                        # Model the stack with newest element first, independently of list.pop().
                        newest = []
                        for move in moves:
                            if move >= 0:
                                newest = [move + total % 5] + newest
                            elif newest:
                                total -= move * newest[0]
                                newest = newest[1:]
                            else:
                                total += move
                        independent = {'total': total, 'stack': newest[::-1]}
                    elif variant == 'document':
                        records = first_json(prompt, 'Records: ')
                        threshold = int(re.search(r'at least (\d+) minutes', prompt)[1])
                        approved = {row['id'] for row in records if row['approved']}
                        selected = approved & {row['id'] for row in records
                                               if row['team'] == 'A' and row['minutes'] >= threshold}
                        independent = {'ids': [row['id'] for row in records if row['id'] in selected],
                                       'minutes': sum(row['minutes'] for row in records if row['id'] in selected)}
                    else:
                        continue
                    with self.subTest(template=variant, level=level, seed=case.seed):
                        self.assertEqual(case.expected, independent)
                    covered.add(variant)
        self.assertEqual(covered, {'constraints', 'constraints_multi', 'code', 'code_branch', 'stack', 'document'})

    def test_new_structures_match_independent_oracles_on_three_levels(self):
        for generate, solve in ORACLES.items():
            for seed in (0, 1, 42, 107, 2147483647):
                for level in (1, 2, 3):
                    with self.subTest(template=generate.__name__, seed=seed, level=level):
                        prompt, actual = generate(random.Random(seed), level)
                        data = json.loads(after(prompt, 'Input JSON: '))
                        self.assertEqual(actual, solve(data))

    def test_existing_exam_structures_match_independent_input_solvers(self):
        for seed in (0, 42, 107):
            for level in (1, 2, 3):
                with self.subTest(seed=seed, level=level):
                    prompt, actual = _dependency(random.Random(seed), level)
                    requested = ast.literal_eval(after(prompt, 'complete tasks ').split('. Each', 1)[0])
                    rows = first_json(prompt, 'rows: ')
                    closure = set(requested)
                    while True:
                        prior = closure.copy()
                        closure |= {parent for name, parents in rows if name in prior for parent in parents}
                        if closure == prior:
                            break
                    self.assertEqual(actual, sorted(closure))

                    prompt, actual = _slice_repair(random.Random(seed), level)
                    values = ast.literal_eval(after(prompt, 'Values: ').split('. Queries', 1)[0])
                    queries = ast.literal_eval(after(prompt, 'stride]: ').rstrip('.'))
                    choices = first_json(prompt, 'every input: ')
                    self.assertEqual(actual, {'option': next(key for key, value in choices.items()
                        if value == 'values[lo-1:hi:stride]'), 'outputs': [[value for position, value
                        in enumerate(values, 1) if lo <= position <= hi and (position - lo) % step == 0]
                        for lo, hi, step in queries]})

                    prompt, actual = _tier_repair(random.Random(seed), level)
                    base, middle, first, high, second = map(int, re.findall(
                        r'base fee is (\d+), the middle fee is (\d+) starting at (\d+), and the high fee is (\d+) starting at (\d+)', prompt)[0])
                    inputs = ast.literal_eval(after(prompt, 'For n values ').split(', return', 1)[0])
                    choices = first_json(prompt, 'expression: ')
                    expression = f'{high} if n >= {second} else {middle} if n >= {first} else {base}'
                    self.assertEqual(actual, {'option': next(k for k, v in choices.items() if v == expression),
                        'fees': [next(fee for threshold, fee in ((second, high), (first, middle), (-999, base))
                                      if n >= threshold) for n in inputs]})

                    prompt, actual = _join(random.Random(seed), level)
                    prices = first_json(prompt, 'Prices: ')
                    orders = first_json(prompt, 'status]: ')
                    cutoff = int(re.search(r'at least (\d+)', prompt)[1])
                    totals = {code: sum(row[2] for row in orders if row[1] == code and row[3] == 'paid')
                              for code in prices}
                    selected = sorted(code for code in prices if totals[code] >= cutoff)
                    self.assertEqual(actual, {'codes': selected,
                        'revenue': sum(row[2] * prices[row[1]] for row in orders
                                       if row[1] in selected and row[3] == 'paid')})

                    prompt, actual = _policy(random.Random(seed), level)
                    rules = first_json(prompt, 'multiplier]: ')
                    records = first_json(prompt, 'approved]: ')
                    totals = {team: sum(row[2] * multiplier for row in records
                                       if row[1] == team and row[3] and row[2] >= minimum)
                              for team, (minimum, multiplier) in rules.items()}
                    winner = sorted(totals, key=lambda name: (-totals[name], name))[0]
                    self.assertEqual(actual, {'winner': winner, 'total': totals[winner],
                        'ids': [row[0] for row in records if row[1] == winner and row[3]
                                and row[2] >= rules[winner][0]]})

                    prompt, actual = _nested(random.Random(seed), level)
                    rows = first_json(prompt, 'active]: ')
                    self.assertEqual(actual, {'entries': [{'code': code,
                        'data': {'values': list(reversed(sorted(values))), 'count': len(values)}}
                        for code, values, active in rows if active]})

                    prompt, actual = _tool_plan(random.Random(seed), level)
                    fields = ast.literal_eval(after(prompt, 'Requested fields: ').split('. Each', 1)[0])
                    ranges = ast.literal_eval(after(prompt, 'count]: ').rstrip('.'))
                    self.assertEqual(actual, {'name': 'preview_records', 'arguments': {
                        'fields': sorted(fields), 'ranges': [{'first': start, 'last': list(range(start, start + count))[-1]}
                        for start, count in ranges], 'options': {'descending': 'set to true' in prompt}}})

    def test_every_template_reappears_exactly_two_or_three_times_per_paper(self):
        for family in EXAM_FAMILIES:
            for samples in (120, 180):
                paper = list(exam_cases(family, samples, 99))
                counts = Counter((case.kind, difficulty, case.variant) for case, difficulty in paper)
                self.assertEqual(set(counts.values()), {samples // 60})

    def test_required_edges_are_present_in_generated_inputs(self):
        prompt, _ = generators.dedup_repair(random.Random(0), 1)
        values = json.loads(after(prompt, 'Input JSON: '))['values']
        self.assertEqual(values[:4], [1, 1, 2, 1])
        prompt, answer = generators.insertion_repair(random.Random(0), 1)
        data = json.loads(after(prompt, 'Input JSON: '))
        self.assertEqual(answer['indices'][:2], [0, len(data['values'])])
        self.assertLess(len(set(data['values'])), len(data['values']))
        prompt, _ = generators.interval_records(random.Random(0), 1)
        data = json.loads(after(prompt, 'Input JSON: '))
        self.assertEqual(data['records'][-2][1], data['start'])
        self.assertEqual(data['records'][-1][1], data['end'])
        self.assertIn(data['records'][-2][0], interval(data)['ids'])
        self.assertNotIn(data['records'][-1][0], interval(data)['ids'])


if __name__ == '__main__':
    unittest.main()
