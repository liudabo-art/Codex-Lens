"""Gemini native papers and independent synthetic answer programs."""
from collections import Counter
from datetime import datetime, timedelta
import itertools
import json
import math
import random
import unicodedata
import unittest

from relay_auditor.exam import exam_cases
from relay_auditor.exam_registry import get_exam_spec, is_exam_suite
from test_native_exam_engine import native_module


def csv_rows(text):
    """Small test-only quoted-field parser independent of csv.DictReader."""
    rows, row, field, quoted, index = [], [], '', False, 0
    while index < len(text):
        char = text[index]
        if char == '"':
            if quoted and index + 1 < len(text) and text[index + 1] == '"':
                field += '"'
                index += 1
            else:
                quoted = not quoted
        elif not quoted and char == ',':
            row.append(field)
            field = ''
        elif not quoted and char == '\n':
            rows.append(row + [field])
            row, field = [], ''
        else:
            field += char
        index += 1
    if row or field:
        rows.append(row + [field])
    return [dict(zip(rows[0], row)) for row in rows[1:]]


def solve(name, data):
    if name == 'gemini_grid_paths':
        blocked = {tuple(cell) for cell in data['blocked']}
        total = 0
        for moves in itertools.product('RD', repeat=data['height'] + data['width'] - 2):
            row = column = 0
            valid = True
            for move in moves:
                row += move == 'D'
                column += move == 'R'
                if (row, column) in blocked or row >= data['height'] or column >= data['width']:
                    valid = False
                    break
            total += valid and (row, column) == (data['height'] - 1, data['width'] - 1)
        return total
    if name == 'gemini_linear_system':
        solutions = [{'x': x, 'y': y} for x in range(-20, 21) for y in range(-20, 21)
                     if all(a * x + b * y == c for a, b, c in data['equations'])]
        assert len(solutions) == 1
        return solutions[0]
    if name == 'gemini_congruence':
        return [n for n in range(data['low'], data['high'] + 1)
                if n not in data['excluded'] and all(n % modulus == residue for modulus, residue in data['rules'])]
    if name == 'gemini_set_expression':
        return [value for value in sorted(set(sum(data['sets'].values(), [])))
                if (((value in data['sets']['A'] or value in data['sets']['B']) and value not in data['sets']['C'])
                    != (value in data['sets']['D']))]
    if name == 'gemini_stable_sort':
        ranks = {}
        for index, row in enumerate(data['rows']):
            ranks[row['id']] = sum((abs(other['score']), other['group'], j) <
                                   (abs(row['score']), row['group'], index)
                                   for j, other in enumerate(data['rows']))
        return sorted(ranks, key=ranks.get)
    if name == 'gemini_histogram_trace':
        result = {}
        for name in sorted({row[0] for row in data['operations']}):
            changes = [delta for key, delta in data['operations'] if key == name]
            prefixes = list(itertools.accumulate(changes))
            final = sum(changes) - min([0] + prefixes)
            if final:
                result[name] = final
        return result
    if name == 'gemini_zip_trace':
        absent = object()
        pairs = list(itertools.zip_longest(data['left'], data['right'], fillvalue=absent))
        return {'total': sum((i + 1) * ((data['fill'] if a is absent else a) -
                                       (data['fill'] if b is absent else b)) for i, (a, b) in enumerate(pairs)),
                'unpaired': [i for i, pair in enumerate(pairs) if absent in pair]}
    if name == 'gemini_modulo_trace':
        quotients = [math.floor(value / data['modulus']) for value in data['values']]
        remainders = [value - q * data['modulus'] for value, q in zip(data['values'], quotients)]
        return {'total': sum(quotients), 'buckets': [remainders.count(i) for i in range(data['modulus'])]}
    if name == 'gemini_clamp_repair':
        option = next(k for k, v in data['choices'].items() if v == 'max(lo, min(hi, x))')
        return {'option': option, 'values': [data['lo'] if x < data['lo'] else data['hi'] if x > data['hi'] else x
                                            for x in data['values']]}
    if name == 'gemini_chunk_repair':
        option = next(k for k, v in data['choices'].items()
                      if v == '[values[i:i+k] for i in range(0, len(values), k)]')
        outputs = []
        for values in data['lists']:
            groups = []
            for index, value in enumerate(values):
                if index % data['width'] == 0:
                    groups.append([])
                groups[-1].append(value)
            outputs.append(groups)
        return {'option': option, 'outputs': outputs}
    if name == 'gemini_filter_repair':
        option = next(k for k, v in data['choices'].items() if v == '(lo <= x <= hi) or (x == special)')
        interval = set(range(data['lo'], data['hi'] + 1)) | {data['special']}
        return {'option': option, 'output': [value for value in data['values'] if value in interval]}
    if name == 'gemini_rotation_repair':
        option = next(k for k, v in data['choices'].items()
                      if v == 'values[k % len(values):] + values[:k % len(values)] if values else []')
        outputs = []
        for values in data['lists']:
            rotations = []
            for shift in data['shifts']:
                rotated = [value for value in values]
                if rotated:
                    for _ in range(shift % len(rotated)):
                        rotated.append(rotated.pop(0))
                rotations.append(rotated)
            outputs.append(rotations)
        return {'option': option, 'outputs': outputs}
    if name == 'gemini_time_normalization':
        instants = [(datetime(2020, 1, 1) + timedelta(days=day, hours=hour, minutes=minute - offset), name)
                    for name, day, hour, minute, offset in data['records']]
        return {'ids': [name for _, name in sorted(instants)],
                'span_minutes': int((max(time for time, _ in instants) - min(time for time, _ in instants)).total_seconds() // 60)}
    if name == 'gemini_unit_conversion':
        def milligrams(row):
            amount = row['amount']
            if row['unit'] == 'kg':
                return amount * 1000 * 1000
            if row['unit'] == 'g':
                return amount * 1000
            return amount
        return {'total_mg': sum(map(milligrams, data['records'])),
                'ids': [row['id'] for row in data['records'] if milligrams(row) >= data['minimum_mg']]}
    if name == 'gemini_csv_records':
        selected = [row for row in csv_rows(data['csv']) if row['enabled'] == 'yes' and row['label'] in data['labels']]
        return {'ids': [row['id'] for row in selected], 'labels': [row['label'] for row in selected],
                'total': sum(int(row['amount']) for row in selected)}
    if name == 'gemini_ranked_ballot':
        first = [next((name for name in ballot if name not in data['withdrawn']), None) for ballot in data['ballots']]
        counts = {name: first.count(name) for name in data['candidates'] if name not in data['withdrawn']}
        return {'counts': counts, 'exhausted': first.count(None),
                'winner': min(counts, key=lambda name: (-counts[name], name))}
    if name == 'gemini_pivot_shape':
        return {'matrix': [[sum(value for row, column, value in data['records'] if row == r and column == c)
                            for c in data['columns']] for r in data['rows']],
                'totals': [sum(value for row, column, value in data['records'] if row == r) for r in data['rows']]}
    if name == 'gemini_json_pointer':
        leaves, pending = [], [([], data['document'])]
        while pending:
            path, value = pending.pop(0)
            if isinstance(value, (dict, list)):
                pairs = value.items() if isinstance(value, dict) else enumerate(value)
                pending.extend((path + [str(key)], child) for key, child in pairs)
            else:
                pointer = '/' + '/'.join(part.replace('~', '~0').replace('/', '~1') for part in path)
                leaves.append({'path': pointer, 'value': value})
        return sorted(leaves, key=lambda row: row['path'])
    if name == 'gemini_multilingual_labels':
        keys = [unicodedata.normalize('NFC', label).casefold() for label in data['labels']]
        return {'groups': [{'key': key, 'count': keys.count(key),
                            'forms': list(dict.fromkeys(label for label, canonical in zip(data['labels'], keys) if canonical == key))}
                           for key in sorted(set(keys))]}
    if name == 'gemini_default_shape':
        result = []
        for row in data['rows']:
            meta = row.get('meta') or {}
            values = {key: meta[key] if key in meta else data['defaults'][key] for key in ('name', 'enabled', 'tags')}
            result.append({'id': row['id'], 'display': values['name'], 'enabled': values['enabled'], 'tags': values['tags']})
        return {'records': result}
    raise AssertionError('missing independent oracle: ' + name)


class GeminiExamTests(unittest.TestCase):
    def test_gemini_has_its_own_balanced_versioned_paper(self):
        try:
            spec = get_exam_spec('gemini')
        except ValueError:
            self.fail('Gemini needs its independent registered exam')
        self.assertEqual(spec.version, 'gemini-exam-v1')
        self.assertTrue(is_exam_suite(spec.version))
        self.assertEqual(spec.max_prompt_bytes, 8192)
        for size in (120, 180):
            paper = tuple(exam_cases('gemini', size, 42, suite_version=spec.version))
            self.assertEqual(len(paper), size)
            self.assertEqual(paper, tuple(exam_cases('gemini', size, 42)))
            self.assertNotEqual(paper, tuple(exam_cases('gemini', size, 43)))
            self.assertEqual(len({case.prompt for case, _ in paper}), size)
            self.assertEqual(len({case.item_id for case, _ in paper}), size)
            self.assertTrue(all(len(case.prompt.encode()) <= spec.max_prompt_bytes for case, _ in paper))
            for start in range(0, size, 60):
                counts = Counter((case.kind, tier, case.variant) for case, tier in paper[start:start + 60])
                self.assertEqual(len(counts), 60)
                self.assertEqual(set(counts.values()), {1})
                self.assertEqual(Counter((kind, tier) for kind, tier, _ in counts),
                                 Counter({(kind, tier): 4 for kind in spec.task_kinds for tier in (1, 2, 3)}))
        for version in ('exam-v2', 'claude-exam-v1', 'future-exam-v9'):
            with self.assertRaises(ValueError):
                tuple(exam_cases('gemini', 120, 42, suite_version=version))

    def test_all_twenty_gemini_templates_match_independent_solvers(self):
        module = native_module()
        generators = getattr(module, 'GEMINI_GENERATORS', ())
        self.assertEqual(len(generators), 5, 'Gemini native generators are missing')
        covered = set()
        for group in generators:
            for generate in group:
                for tier in (1, 2, 3):
                    for seed in (0, 1, 42, 107, 2147483647):
                        with self.subTest(template=generate.__name__, tier=tier, seed=seed):
                            prompt, answer = generate(random.Random(seed), tier)
                            data = json.loads(prompt.split('Input JSON: ', 1)[1])
                            self.assertEqual(json.dumps(answer, sort_keys=True),
                                             json.dumps(solve(generate.__name__, data), sort_keys=True))
                            self.assertLessEqual(len(prompt.encode()) + 100, 8192)
                            covered.add(generate.__name__)
        self.assertEqual(len(covered), 20)

    def test_required_unicode_quoting_negative_and_empty_edges_are_present(self):
        module = native_module()
        self.assertTrue(hasattr(module, 'GEMINI_GENERATORS'), 'Gemini generators are missing')
        for tier in (1, 2, 3):
            for name in ('gemini_csv_records', 'gemini_json_pointer', 'gemini_multilingual_labels',
                         'gemini_rotation_repair', 'gemini_modulo_trace', 'gemini_chunk_repair',
                         'gemini_time_normalization'):
                prompt, answer = getattr(module, name)(random.Random(42), tier)
                data = json.loads(prompt.split('Input JSON: ', 1)[1])
                if name == 'gemini_csv_records':
                    self.assertIn('""', data['csv'])
                    self.assertIn('line\nbreak', data['csv'])
                elif name == 'gemini_json_pointer':
                    self.assertTrue(any('~1' in row['path'] for row in answer))
                    self.assertTrue(any('~0' in row['path'] for row in answer))
                elif name == 'gemini_multilingual_labels':
                    self.assertIn('é', data['labels'])
                    self.assertIn('e\u0301', data['labels'])
                    self.assertIn('Straße', data['labels'])
                    self.assertIn('STRASSE', data['labels'])
                elif name in ('gemini_rotation_repair', 'gemini_chunk_repair'):
                    self.assertEqual(data['lists'][0], [])
                elif name == 'gemini_modulo_trace':
                    self.assertTrue(any(value < 0 and value % data['modulus'] for value in data['values']))
                else:
                    instants = [day * 1440 + hour * 60 + minute - offset
                                for _, day, hour, minute, offset in data['records']]
                    self.assertLess(min(instants), 0)
                    self.assertGreater(max(instants), 1440)
