"""Native exam contracts and independent, input-derived answer programs."""
from collections import Counter
from dataclasses import FrozenInstanceError
import hashlib
import importlib
import itertools
import json
import random
import unittest
from pathlib import Path

from relay_auditor.exam import exam_cases


def native_module():
    try:
        return importlib.import_module('relay_auditor.native_exam_generators')
    except ModuleNotFoundError:
        return None


def solve(name, data):
    """Test-only solvers never call a production oracle or execute response text."""
    if name == 'claude_assignment':
        feasible = []
        for values in itertools.permutations(data['people']):
            placement = dict(zip(data['slots'], values))
            if all(placement[slot] in allowed for slot, allowed in data['allowed'].items()):
                feasible.append(values)
        return dict(zip(data['slots'], min(feasible)))
    if name == 'claude_precedence':
        orders = (order for order in itertools.permutations(data['names'])
                  if all(order.index(left) < order.index(right) for left, right in data['before']))
        return list(min(orders))
    if name == 'claude_truth_models':
        models = []
        for bits in itertools.product((False, True), repeat=len(data['names'])):
            values = dict(zip(data['names'], bits))
            if sum(bits) != data['true_count']:
                continue
            if all((not values[a] or values[b]) if op == 'implies' else
                   (values[a] != values[b]) if op == 'xor' else
                   (values[a] == values[b]) for op, a, b in data['rules']):
                models.append(values)
        return {'count': len(models), 'forced': {name: models[0][name] for name in data['names']
                 if all(model[name] == models[0][name] for model in models)}}
    if name == 'claude_interval_choice':
        candidates = []
        for count in range(len(data['jobs']) + 1):
            for rows in itertools.combinations(data['jobs'], count):
                if all(a[2] <= b[1] or b[2] <= a[1] for a, b in itertools.combinations(rows, 2)):
                    ids = sorted(row[0] for row in rows)
                    candidates.append((-sum(row[3] for row in rows), ids))
        value, ids = min(candidates)
        return {'ids': ids, 'value': -value}
    if name == 'claude_alias_trace':
        # Object IDs model references; immutable tuples model each object's contents.
        objects = {0: tuple(data['initial'])}
        refs = {'a': 0, 'b': 0, 'c': 1}
        objects[1] = tuple(data['initial'])
        for target, op, value in data['operations']:
            ref = refs[target]
            if op == 'append':
                objects[ref] += (value,)
            elif op == 'trim':
                objects[ref] = objects[ref][:-1]
            else:
                new_ref = len(objects)
                objects[new_ref] = objects[ref] + (value,)
                refs[target] = new_ref
        return {key: list(objects[ref]) for key, ref in refs.items()}
    if name == 'claude_loop_else':
        first = [next((i for i, x in enumerate(row) if x == data['stop']), len(row))
                 for row in data['rows']]
        return {'total': sum(sum(row[:index]) for row, index in zip(data['rows'], first)),
                'clean': [i for i, (row, index) in enumerate(zip(data['rows'], first)) if index == len(row)]}
    if name == 'claude_slice_trace':
        original = data['values']
        indices = list(range(len(original)))[data['start']:data['stop']:data['step']]
        replacements = dict(zip(indices, data['replacement']))
        return [replacements.get(i, x) for i, x in enumerate(original)]
    if name == 'claude_finally_trace':
        total = data['initial'] + sum((data['numerator'] // d if d else 0) + data['bonus']
                                      for d in data['divisors'])
        return {'total': total, 'skipped': data['divisors'].count(0)}
    if name == 'claude_lookup_repair':
        option = next(k for k, v in data['choices'].items() if v == 'mapping[key] if key in mapping else default')
        return {'option': option, 'values': [next((v for k, v in data['mapping'].items() if k == q),
                                                 data['default']) for q in data['queries']]}
    if name == 'claude_window_repair':
        option = next(k for k, v in data['choices'].items() if v == 'range(max(0, len(values)-k+1))')
        return {'option': option, 'windows': [[[x for j, x in enumerate(data['values']) if i <= j < i + k]
                 for i in range(len(data['values']) + 1) if i + k <= len(data['values'])] for k in data['widths']]}
    if name == 'claude_partition_repair':
        option = next(k for k, v in data['choices'].items() if v == 'negatives + nonnegatives')
        indexed = sorted(enumerate(data['values']), key=lambda pair: (pair[1] >= 0, pair[0]))
        return {'option': option, 'output': [value for _, value in indexed]}
    if name == 'claude_merge_repair':
        option = next(k for k, v in data['choices'].items() if v == 'start < merged[-1][1]')
        components = []
        for start, end in sorted(data['intervals']):
            component = [interval for interval in components if start < interval[1]]
            if component:
                component[0][1] = max(end, component[0][1])
            else:
                components.append([start, end])
        return {'option': option, 'intervals': components}
    if name == 'claude_document_revision':
        latest = {name: max((row for row in data['rows'] if row['id'] == name), key=lambda row: row['revision'])
                  for name in {row['id'] for row in data['rows']}}
        kept = [row for row in latest.values() if not row['deleted']]
        return {'ids': sorted(row['id'] for row in kept), 'total': sum(row['amount'] for row in kept)}
    if name == 'claude_policy_exception':
        decisions = []
        for row in data['records']:
            matching = [r['effect'] for r in data['rules']
                        if r['team'] in ('*', row['team']) and row['amount'] >= r['minimum']]
            decisions.append('deny' if 'deny' in matching else 'allow' if 'allow' in matching else 'deny')
        return {'ids': [r['id'] for r, decision in zip(data['records'], decisions) if decision == 'allow']}
    if name == 'claude_cross_reference':
        totals = {name: sum(item['units'] for item in data['orders'] if item['project'] == name and item['approved']
                           and any(c['code'] == item['code'] and c['active'] for c in data['catalog']))
                  for name in data['projects']}
        return {'totals': totals, 'qualifying': sorted(name for name, total in totals.items() if total >= data['minimum'])}
    if name == 'claude_event_retraction':
        active = {}
        for event in data['events']:
            if event['op'] == 'put':
                active[event['id']] = event['value']
            elif event['id'] in active:
                del active[event['id']]
        return {'ids': sorted(active), 'total': sum(active.values())}
    if name == 'claude_instruction_scope':
        # Select matching rows by the outer rule, ignoring every quoted directive.
        kept = [r for r in data['rows'] if r['tag'] == data['select_tag']]
        return {'selected': [r['id'] for r in kept], 'count': len(kept)}
    if name == 'claude_projection':
        return {'entries': [{'name': r['label'], 'metrics': {'count': r['quantity'], 'enabled': r['active']}}
                            for r in data['rows'] if r['active']]}
    if name == 'claude_null_shape':
        return [{'id': row['id'], 'state': ('missing' if 'value' not in row else 'null' if row['value'] is None
                else 'present'), 'value': row.get('value')} for row in data['rows']]
    if name == 'claude_quoted_extract':
        return {'texts': [json.loads(row['encoded']) for row in data['rows'] if row['tag'] == data['select_tag']]}
    raise AssertionError('missing independent oracle: ' + name)


class NativeExamTests(unittest.TestCase):
    def test_negative_slice_null_stop_need_not_select_index_zero(self):
        prompt, answer = native_module().claude_slice_trace(random.Random(2), 2)
        data = json.loads(prompt.split('Input JSON: ', 1)[1])
        self.assertEqual((data['start'], data['stop'], data['step']), (8, None, -3))
        self.assertEqual(list(range(len(data['values'])))[data['start']:data['stop']:data['step']], [8, 5, 2])
        self.assertEqual(answer[0], data['values'][0])
        self.assertEqual([answer[i] for i in (8, 5, 2)], data['replacement'])
        # A literal zero stop excludes index 0; None allows it when the stride
        # reaches it. The question must explain both cases without contradiction.
        for seed, stop, indices in ((0, 0, [8, 6, 4, 2]), (4, None, [8, 6, 4, 2, 0])):
            prompt, answer = native_module().claude_slice_trace(random.Random(seed), 2)
            data = json.loads(prompt.split('Input JSON: ', 1)[1])
            self.assertEqual((data['start'], data['stop'], data['step']), (8, stop, -2))
            self.assertEqual(list(range(len(data['values'])))[data['start']:data['stop']:data['step']], indices)
            self.assertEqual(answer[0] == data['values'][0], stop == 0)
            self.assertIn('negative step and stop=null', prompt)
            self.assertIn('literal stop=0 excludes index 0', prompt)

    def test_native_versions_keep_frozen_prompts_answers_and_seed_mapping(self):
        baseline = json.loads(Path(__file__).with_name('native_exam_papers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(baseline), 12)
        for row in baseline:
            with self.subTest(family=row['family'], samples=row['samples'], seed=row['seed']):
                paper = [{'kind': case.kind, 'seed': case.seed, 'prompt': case.prompt,
                          'expected': case.expected, 'variant': case.variant, 'difficulty': level}
                         for case, level in exam_cases(row['family'], row['samples'], row['seed'],
                                                     suite_version=row['version'])]
                actual = hashlib.sha256(json.dumps(paper, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(actual, row['sha256'])

    def test_legacy_twelve_papers_keep_frozen_prompts_answers_and_seed_mapping(self):
        baseline = json.loads(Path(__file__).with_name('legacy_exam_papers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(baseline), 12)
        for row in baseline:
            with self.subTest(family=row['family'], samples=row['samples'], seed=row['seed']):
                paper = [{'kind': case.kind, 'seed': case.seed, 'prompt': case.prompt,
                          'expected': case.expected, 'variant': case.variant, 'difficulty': level}
                         for case, level in exam_cases(row['family'], row['samples'], row['seed'])]
                actual = hashlib.sha256(json.dumps(paper, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(actual, row['sha256'])

    def test_claude_balanced_independent_versioned_bounded_papers(self):
        try:
            paper = tuple(exam_cases('claude', 120, 42))
        except ValueError:
            self.fail('Claude needs its independent full exam')
        registry = importlib.import_module('relay_auditor.exam_registry')
        spec = registry.get_exam_spec('claude')
        self.assertEqual(spec.version, 'claude-exam-v1')
        self.assertEqual(spec.max_prompt_bytes, 8192)
        with self.assertRaises(FrozenInstanceError):
            spec.family = 'gpt'
        self.assertTrue(registry.is_exam_suite(spec.version))
        self.assertFalse(registry.is_exam_suite('not-an-exam'))
        self.assertIn(spec.version, registry.exam_suite_versions())
        for samples in spec.sizes:
            paper = tuple(exam_cases('claude', samples, 42, suite_version=spec.version))
            self.assertEqual(paper, tuple(exam_cases('claude', samples, 42)))
            self.assertNotEqual(paper, tuple(exam_cases('claude', samples, 43)))
            self.assertEqual(len({case.prompt for case, _ in paper}), samples)
            self.assertEqual(len({case.item_id for case, _ in paper}), samples)
            self.assertTrue(all(len(case.prompt.encode()) <= spec.max_prompt_bytes for case, _ in paper))
            for start in range(0, samples, 60):
                counts = Counter((case.kind, level, case.variant) for case, level in paper[start:start + 60])
                self.assertEqual(len(counts), 60)
                self.assertEqual(set(counts.values()), {1})
                self.assertEqual(Counter((kind, level) for kind, level, _ in counts),
                                 Counter({(kind, level): 4 for kind in spec.task_kinds for level in (1, 2, 3)}))
        for family, version in [('gpt', 'claude-exam-v1'), ('claude', 'exam-v2'), ('claude', 'future-exam-v9')]:
            with self.assertRaises(ValueError):
                tuple(exam_cases(family, 120, 42, suite_version=version))

    def test_every_claude_template_matches_independent_solver_all_tiers(self):
        module = native_module()
        self.assertIsNotNone(module, 'native generators are missing')
        covered = set()
        for group in module.CLAUDE_GENERATORS:
            for generate in group:
                for level in (1, 2, 3):
                    for seed in (0, 1, 42, 107, 2147483647):
                        with self.subTest(template=generate.__name__, level=level, seed=seed):
                            prompt, answer = generate(random.Random(seed), level)
                            data = json.loads(prompt.split('Input JSON: ', 1)[1])
                            self.assertEqual(json.dumps(answer, sort_keys=True),
                                             json.dumps(solve(generate.__name__, data), sort_keys=True))
                            self.assertLessEqual(len(prompt.encode()) + 100, 8192)
                            covered.add(generate.__name__)
        self.assertEqual(len(covered), 20)

    def test_claude_code_and_document_edges_are_always_present(self):
        module = native_module()
        self.assertIsNotNone(module, 'native generators are missing')
        for level in (1, 2, 3):
            for name in ('claude_lookup_repair', 'claude_window_repair', 'claude_merge_repair',
                         'claude_document_revision', 'claude_instruction_scope', 'claude_null_shape'):
                prompt, answer = getattr(module, name)(random.Random(1), level)
                data = json.loads(prompt.split('Input JSON: ', 1)[1])
                if name == 'claude_lookup_repair':
                    self.assertTrue(all(value in data['mapping'].values() for value in (None, False, 0, '')))
                    self.assertIn('missing', data['queries'])
                elif name == 'claude_window_repair':
                    self.assertIn(0, data['widths'])
                    self.assertIn(len(data['values']) + 1, data['widths'])
                elif name == 'claude_merge_repair':
                    self.assertTrue(any(a[1] == b[0] for a, b in itertools.permutations(data['intervals'], 2)))
                elif name == 'claude_document_revision':
                    self.assertTrue(any(row['deleted'] for row in data['rows']))
                    self.assertTrue(any('Ignore' in row['note'] for row in data['rows']))
                elif name == 'claude_instruction_scope':
                    self.assertTrue(any('Ignore' in row['text'] for row in data['rows']))
                else:
                    self.assertEqual({row['state'] for row in answer}, {'missing', 'null', 'present'})
