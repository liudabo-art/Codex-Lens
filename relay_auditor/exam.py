"""Reproducible exam-v2 papers and strict, budgeted submission."""
from collections import Counter
from dataclasses import dataclass
import json
import random

from .families import family_for
from .grading import grade_answer, item_result
from .exam_generators import (shortest_path, schedule, registers, state_machine,
                              dedup_repair, insertion_repair, ledger, interval_records,
                              grouped_shape, sparse_shape)
from .protocol import ProbeCase
from .suites import quality_case
from .transport import EndpointError


EXAM_VERSION = 'exam-v2'
EXAM_MODE = 'capability_exam'
EXAM_FAMILIES = ('gpt', 'deepseek')
EXAM_SIZES = (120, 180)
EXAM_MAX_PROMPT_BYTES = 4096
EXAM_TASKS = ('exam_reasoning', 'exam_code', 'exam_repair', 'exam_information', 'exam_structure')
RETRYABLE = frozenset(('network_error', 'stream_interrupted', 'empty_answer'))
RESPONSE_ISSUES = RETRYABLE | {'output_limit', 'response_filtered', 'incomplete_output'}
ANSWER_INSTRUCTION = '\nReturn only a JSON object with the sole key "answer". Do not use tools.'


@dataclass(frozen=True)
class ExamCase(ProbeCase):
    variant: str = ''


def _dependency(rng, level):
    """Follow prerequisite edges rather than solve a bounded optimization."""
    count = 4 + 3 * level
    ids = rng.sample(range(10, 90), count)
    rows = {ids[0]: []}
    for index, key in enumerate(ids[1:], 1):
        parents = rng.sample(ids[:index], min(index, level))
        rows[key] = sorted(parents)
    requested = ids[-(1 if level == 1 else 2):]
    seen = set(requested)
    pending = list(requested)
    while pending:
        for parent in rows[pending.pop()]:
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return (
        f'You must complete tasks {requested}. Each row lists direct prerequisites that must also be completed. '
        'Dependencies apply recursively. Return the ascending list of all tasks that must be completed, '
        f'including the requested tasks. Task-to-prerequisite rows: {json.dumps(sorted(rows.items()))}',
        sorted(seen),
    )


def _stack(rng, level):
    initial = rng.randint(1, 20)
    moves = [rng.randint(1, 7), -1]
    moves.extend(rng.randint(-4, 7) for _ in range(4 + level * 6))
    stack = []
    total = initial
    for move in moves:
        if move >= 0:
            stack.append(move + total % 5)
        elif stack:
            total += stack.pop() * -move
        else:
            total += move
    return (
        'Trace this Python program. Return an object with keys "stack" and "total" holding their final values.\n'
        f'moves = {moves!r}\ntotal = {initial}\nstack = []\n'
        'for move in moves:\n'
        '    if move >= 0:\n'
        '        stack.append(move + total % 5)\n'
        '    elif stack:\n'
        '        total += stack.pop() * -move\n'
        '    else:\n'
        '        total += move',
        {'stack': stack, 'total': total},
    )


def _slice_repair(rng, level):
    values = rng.sample(range(10, 99), 5 + level * 3)
    queries = [(1, len(values), level), (len(values), len(values), 1)]
    for _ in range(1 + level):
        left = rng.randrange(1, len(values) + 1)
        queries.append((left, rng.randrange(left, len(values) + 1), rng.randint(1, level + 1)))
    correct = 'values[lo-1:hi:stride]'
    choices = [correct, 'values[lo:hi:stride]', 'values[lo-1:hi-1:stride]', 'values[lo:hi+1:stride]']
    rng.shuffle(choices)
    outputs = [values[left - 1:right:stride] for left, right, stride in queries]
    return (
        'Repair a Python slice. The function must select positions lo through hi, both inclusive, using '
        'one-based positions, starting at lo and advancing the position by stride after each item. '
        'All bounds are valid. '
        f'Choose the expression that works for every input: {json.dumps(dict(zip("ABCD", choices)))}. '
        'Return an object with "option" (its letter) and "outputs" (lists returned for each given query). '
        f'Values: {values!r}. Queries [lo, hi, stride]: {queries!r}.',
        {'option': 'ABCD'[choices.index(correct)], 'outputs': outputs},
    )


def _tier_repair(rng, level):
    first = rng.randint(10, 30)
    second = first + rng.randint(3, 9)
    fees = rng.sample(range(1, 10), 3)
    choices = [
        f'{fees[2]} if n >= {second} else {fees[1]} if n >= {first} else {fees[0]}',
        f'{fees[2]} if n > {second} else {fees[1]} if n > {first} else {fees[0]}',
        f'{fees[1]} if n >= {first} else {fees[2]} if n >= {second} else {fees[0]}',
        f'{fees[2]} if n >= {second} else {fees[0]} if n >= {first} else {fees[1]}',
    ]
    correct = choices[0]
    rng.shuffle(choices)
    inputs = [first - 1, first, second - 1, second, second + 1]
    inputs.extend(rng.randint(first - 5, second + 5) for _ in range(level * 2))
    rng.shuffle(inputs)
    return (
        f'Repair this fee rule. The base fee is {fees[0]}, the middle fee is {fees[1]} starting at {first}, '
        f'and the high fee is {fees[2]} starting at {second}. Thresholds are inclusive, and the highest '
        f'applicable tier wins. Choose the correct Python expression: {json.dumps(dict(zip("ABCD", choices)))}. '
        f'For n values {inputs!r}, return an object with "option" (the letter) and "fees" (resulting list).',
        {'option': 'ABCD'[choices.index(correct)],
         'fees': [fees[2] if n >= second else fees[1] if n >= first else fees[0] for n in inputs]},
    )


def _join(rng, level):
    codes = list('ABCDEFGH')[:4 + level]
    prices = {code: rng.randint(2, 15) for code in codes}
    cutoff = rng.randint(5, 10)
    orders = [(index, rng.choice(codes + ['X']), rng.randint(1, 9), rng.choice(['paid', 'open']))
              for index in range(5 + 4 * level)]
    valid = [row for row in orders if row[1] in prices and row[3] == 'paid']
    totals = {}
    for _, code, quantity, _ in valid:
        totals[code] = totals.get(code, 0) + quantity
    codes_to_report = sorted(code for code, quantity in totals.items() if quantity >= cutoff)
    return (
        'Join orders to the product price table by product code. Ignore unpaid orders and orders for '
        f'unknown products. Only report products with total paid quantity of at least {cutoff}. '
        'Return an object with "codes" (sorted qualifying product codes) and "revenue" (sum of price times '
        f'total quantity over qualifying codes). Prices: {json.dumps(prices)}. '
        f'Orders [ID, product, quantity, status]: {json.dumps(orders)}.',
        {'codes': codes_to_report, 'revenue': sum(prices[code] * totals[code] for code in codes_to_report)},
    )


def _policy(rng, level):
    teams = list('ABCDE')[:2 + level]
    rules = {team: [rng.randint(12, 35), rng.randint(1, 3)] for team in teams}
    records = [(index, rng.choice(teams), rng.randint(10, 45), rng.choice([True, True, False]))
               for index in range(6 + 5 * level)]
    qualifying = [row for row in records if row[3] and row[2] >= rules[row[1]][0]]
    amounts = {team: 0 for team in teams}
    for _, team, amount, _ in qualifying:
        amounts[team] += amount * rules[team][1]
    winner = min(teams, key=lambda team: (-amounts[team], team))
    return (
        'Consider approved records only. Each team has an inclusive minimum qualifying amount and '
        'a multiplier for qualifying records. Sum weighted amounts per team. Select the team with '
        'the highest sum, breaking ties by alphabetical team name. Teams with no qualifying records '
        'have sum zero. Return an object with "winner", "total" (its weighted sum), and "ids" '
        f'(its qualifying record IDs in input order). Team rules [minimum, multiplier]: {json.dumps(rules)}. '
        f'Records [ID, team, amount, approved]: {json.dumps(records)}.',
        {'winner': winner, 'total': amounts[winner], 'ids': [row[0] for row in qualifying if row[1] == winner]},
    )


def _nested(rng, level):
    items = [(code, rng.sample(range(1, 30), level + 1), rng.choice([True, False]))
             for code in rng.sample(list('ABCDEFGHIJ'), 3 + 2 * level)]
    selected = [(code, sorted(values, reverse=True)) for code, values, active in items if active]
    return (
        'Convert the active rows to the specified object shape. Keep their input order. '
        'Return an object with the sole key "entries", an array of objects with exactly the keys "code" '
        'and "data". In each entry, "data" is an object with exactly "values" (the integer values in '
        'descending order) and "count" (the number of values). An empty result must use an empty array. '
        f'Rows [code, values, active]: {json.dumps(items)}.',
        {'entries': [{'code': code, 'data': {'values': values, 'count': len(values)}} for code, values in selected]},
    )


def _tool_plan(rng, level):
    ranges = [(rng.randint(1, 40), rng.randint(1, 5)) for _ in range(1 + level)]
    field_names = rng.sample(['id', 'state', 'team', 'quantity', 'name', 'date'], 1 + level)
    descending = rng.choice([True, False])
    return (
        'Describe a virtual call, without executing it. Return an object with exactly "name" and '
        '"arguments". The name must be "preview_records". The arguments object has exactly "fields" '
        '(requested names sorted alphabetically), "ranges" (in input order, an array of objects '
        'with exactly "first" and "last" inclusive), and "options" (an object with one boolean key '
        f'"descending" set to {str(descending).lower()}). Requested fields: {field_names!r}. '
        f'Each range is given as [first, count]: {ranges!r}.',
        {'name': 'preview_records', 'arguments': {
            'fields': sorted(field_names),
            'ranges': [{'first': start, 'last': start + count - 1} for start, count in ranges],
            'options': {'descending': descending},
        }},
    )


PROFILES = {
    'gpt': (('constraints', _dependency, shortest_path, schedule),
            ('code_branch', _stack, registers, state_machine),
            ('repair_edges', _slice_repair, dedup_repair, insertion_repair),
            ('document', _join, ledger, interval_records),
            (_nested, _tool_plan, grouped_shape, sparse_shape)),
    'deepseek': (('constraints_multi', _dependency, shortest_path, schedule),
                 ('code', _stack, registers, state_machine),
                 (_tier_repair, _slice_repair, dedup_repair, insertion_repair),
                 (_policy, _join, ledger, interval_records),
                 (_nested, _tool_plan, grouped_shape, sparse_shape)),
}


def exam_cases(family, samples, seed):
    """Yield each of four structures once per skill/tier in each seeded 60-item block."""
    if (family not in PROFILES or type(samples) is not int or samples not in EXAM_SIZES
            or type(seed) is not int or not 0 <= seed < 2**31):
        raise ValueError('invalid_exam_paper')
    blueprint = [(kind, level, variant) for kind, variants in zip(EXAM_TASKS, PROFILES[family])
                 for level in (1, 2, 3) for variant in variants]
    order_rng = random.Random(seed)
    seen = set()
    for start in range(0, samples, 60):
        block = blueprint.copy()
        order_rng.shuffle(block)
        for offset, (kind, level, variant) in enumerate(block):
            question_seed = seed + start + offset
            for collision in range(32):
                generation_seed = question_seed + collision * 2**32
                if isinstance(variant, str):
                    case = quality_case(variant, generation_seed, difficulty=level)
                    prompt, expected = case.prompt, case.expected
                    variant_name = variant
                else:
                    prompt, expected = variant(random.Random(generation_seed), level)
                    prompt += ANSWER_INSTRUCTION
                    variant_name = variant.__name__.lstrip('_')
                if prompt not in seen:
                    break
            else:
                raise EndpointError('invalid_synthetic_case')
            if len(prompt.encode()) > EXAM_MAX_PROMPT_BYTES:
                raise EndpointError('invalid_synthetic_case')
            seen.add(prompt)
            yield ExamCase(kind, question_seed, prompt, expected, variant_name), level


def _side_counts(source_kind, samples):
    return {
        'source_kind': source_kind, 'sample_count': samples, 'attempted': 0, 'completed': 0,
        'correct': 0, 'format_failures': 0, 'format_recovered': 0, 'retry_requests': 0,
    }


def run_exam(service, monitor, plan, result, *, seed):
    """Execute a locked paper; no score or formal test is issued on a partial paper."""
    from .assessment import RETRY_DELAYS, assessment_comparison
    from .controller import Cancelled
    from .storage import BudgetExceeded

    samples = plan['sample_count']
    paired = plan['comparison'] == 'paired'
    family = family_for(monitor.target.model)
    sides = {source: _side_counts(source, samples) for source in (('relay', 'reference') if paired else ('relay',))}
    sections = {
        (source, task, difficulty): {
            'source_kind': source, 'task_kind': task, 'difficulty': difficulty,
            'sample_count': samples // 15, 'completed': 0, 'correct': 0,
            'format_failures': 0, 'format_recovered': 0,
        }
        for source in sides for task in EXAM_TASKS for difficulty in (1, 2, 3)
    }
    exam = {'comparison': plan['comparison'], 'submitted': False, 'sides': list(sides.values()),
            'sections': list(sections.values())}
    result.update(
        exam=exam, suite_version=EXAM_VERSION, model_family=family, task_seed=seed, task_count=samples,
        sample_count=plan['required_requests'], capability_state='insufficient_data', identity_state='not_tested',
        capability_attempted=0, capability_completed=0, capability_valid=0, capability_correct=0,
        response_count=0, network_failures=0, invalid_responses=0, retry_requests=0, response_issues=[],
    )
    cases = tuple(exam_cases(family, samples, seed))
    items = {(question, source): item_result(case, difficulty, question, source)
             for question, (case, difficulty) in enumerate(cases, 1) for source in sides}
    result['item_results'] = list(items.values())
    diagnostics = Counter()
    grading_diagnostics = Counter()
    pairs = []
    retry_limit = samples // 5
    batch = service.store.reserve_batch(plan['max_requests'], plan['per_call'])

    def read(case, difficulty, source, question):
        side = sides[source]
        section = sections[source, case.kind, difficulty]
        item = items[question, source]
        try:
            for attempt in range(len(RETRY_DELAYS) + 1):
                if not service.store.available(0, 0):
                    raise BudgetExceeded()
                before = service.progress.get('completed', 0)
                response = None
                try:
                    response = service._call(monitor, case, reference=source == 'reference', batch=batch)
                except EndpointError as error:
                    issue = str(error)
                    if service.progress.get('completed', 0) > before:
                        result['network_failures'] += 1
                else:
                    result['response_count'] += 1
                    if response.issue:
                        issue = response.issue if response.issue in RESPONSE_ISSUES else 'incomplete_output'
                    elif not response.complete:
                        issue = 'incomplete_output'
                    else:
                        issue = None if response.text.strip() else 'empty_answer'
                finally:
                    if service.progress.get('completed', 0) > before:
                        item['attempts'] += 1
                        if attempt:
                            side['retry_requests'] += 1
                            result['retry_requests'] += 1
                            service.set_progress(plan['required_requests'] + result['retry_requests'])
                        else:
                            side['attempted'] += 1

                if issue is None:
                    grade = grade_answer(case, response.text)
                    item.update(grade)
                    correct = grade['correct'] is True
                    formatting = grade['error_code']
                    for counts in (side, section):
                        counts['completed'] += 1
                        counts['correct'] += int(correct)
                        counts['format_failures'] += int(formatting == 'answer_format')
                        counts['format_recovered'] += int(formatting == 'recovered_format')
                    if formatting:
                        diagnostics[source, formatting] += 1
                    if grade['grading_issue']:
                        grading_diagnostics[source, grade['grading_issue']] += 1
                    service.set_exam_progress(exam['sides'])
                    if monitor.cancel.is_set() or service.stop_event.is_set():
                        raise Cancelled()
                    return correct

                diagnostics[source, issue] += 1
                item.update(error_code=issue, grading_issue=None)
                if response is not None:
                    result['invalid_responses'] += 1
                if (issue not in RETRYABLE or attempt == len(RETRY_DELAYS)
                        or side['retry_requests'] >= retry_limit):
                    raise EndpointError(issue)
                service.set_retry_progress({'source_kind': source, 'retry_question': question,
                                            'retry_attempt': attempt + 1})
                service.wait_for_retry(monitor, RETRY_DELAYS[attempt])
        except (Exception, KeyboardInterrupt):
            result.update(failure_source=source, failure_question=question)
            raise
        finally:
            service.set_retry_progress(None)

    try:
        service.set_progress(plan['required_requests'])
        service.set_exam_progress(exam['sides'])
        for question, (case, difficulty) in enumerate(cases, 1):
            if not paired:
                read(case, difficulty, 'relay', question)
            elif question % 2:
                target = read(case, difficulty, 'relay', question)
                reference = read(case, difficulty, 'reference', question)
                pairs.append((reference, target))
            else:
                reference = read(case, difficulty, 'reference', question)
                target = read(case, difficulty, 'relay', question)
                pairs.append((reference, target))
        if paired:
            index, alpha = service.store.next_audit()
            comparison = assessment_comparison(pairs, samples, alpha=alpha)
            result.update(paired_result=comparison, audit_index=index, capability_state=comparison['status'],
                          detected_anomaly=comparison['status'] == 'degraded',
                          provenance_level='same_time_official_reference')
        else:
            result['capability_state'] = ('observed_answers_correct' if sides['relay']['correct'] == samples
                                          else 'screening_failure')
        exam['submitted'] = True
        return result
    finally:
        target = sides['relay']
        result.update(
            capability_attempted=target['attempted'], capability_completed=target['completed'],
            capability_valid=target['completed'], capability_correct=target['correct'],
            response_issues=[{'source_kind': source, 'error_code': code, 'sample_count': count}
                             for (source, code), count in diagnostics.items()],
            grading_issues=[{'source_kind': source, 'grading_issue': issue, 'sample_count': count}
                            for (source, issue), count in grading_diagnostics.items()],
        )
        service.store.release_batch(batch)
