"""Additional exam-v2 structures with synthetic inputs and deterministic oracles."""
import json


def _input(prompt, data):
    return prompt + '\nInput JSON: ' + json.dumps(data, separators=(',', ':'))


def shortest_path(rng, level):
    nodes = list('ABCDEFGH')[:4 + level]
    edges = [[nodes[i], nodes[i + 1], rng.randint(1, 9)] for i in range(len(nodes) - 1)]
    for i in range(len(nodes) - 2):
        for j in range(i + 2, len(nodes)):
            if rng.randrange(3) == 0:
                edges.append([nodes[i], nodes[j], rng.randint(1, 15)])
    distances = {nodes[0]: 0}
    for node in nodes:
        for source, target, weight in edges:
            if source == node:
                cost = distances[source] + weight
                distances[target] = min(distances.get(target, cost), cost)
    return _input(
        'Find the minimum total edge weight from start to goal in this directed acyclic graph. '
        'Edges [source,target,weight] may only be followed in their given direction. '
        'Return the minimum weight as an integer.',
        {'start': nodes[0], 'goal': nodes[-1], 'edges': edges}), distances[nodes[-1]]


def schedule(rng, level):
    names = rng.sample(list('ABCDEFGH'), 3 + level)
    rows = []
    finish = {}
    for index, name in enumerate(names):
        parents = rng.sample(names[:index], min(index, rng.randint(0, level)))
        duration = rng.randint(1, 8)
        rows.append([name, duration, sorted(parents)])
        finish[name] = duration + max((finish[parent] for parent in parents), default=0)
    rng.shuffle(rows)
    return _input(
        'Tasks may run in parallel with unlimited workers. A task starts at time 0 if it has no '
        'prerequisites; otherwise it starts as soon as every prerequisite finishes. '
        'Rows [task,duration,prerequisites] are unordered. Return an object with "finish" '
        '(each task name mapped to its earliest finish time) and "makespan" (all tasks finish).',
        {'tasks': rows}), {'finish': finish, 'makespan': max(finish.values())}


def registers(rng, level):
    initial = {'a': rng.randint(-4, 5), 'b': rng.randint(1, 7)}
    instructions = [[rng.choice(['a', 'b']), rng.choice(['add', 'swap', 'mix']), rng.randint(-2, 4)]
                    for _ in range(3 + level * 3)]
    registers = initial.copy()
    for target, operation, amount in instructions:
        other = 'b' if target == 'a' else 'a'
        if operation == 'add':
            registers[target] += amount
        elif operation == 'swap':
            registers[target], registers[other] = registers[other], registers[target]
        else:
            registers[target] = 2 * registers[other] - amount
    return _input(
        'Trace register instructions [target,operation,amount] in order. add adds amount to target. '
        'swap exchanges a and b and ignores amount. mix sets target to twice the OTHER register '
        'minus amount, using its current value. Return an object with final integer keys "a" and "b".',
        {'initial': initial, 'instructions': instructions}), registers


def state_machine(rng, level):
    transitions = {state: {event: rng.choice(['idle', 'open', 'closed']) for event in ['tick', 'reset']}
                   for state in ['idle', 'open', 'closed']}
    events = [rng.choice(['tick', 'reset']) for _ in range(4 + level * 4)]
    initial = rng.choice(list(transitions))
    state = initial
    visits = {name: 0 for name in transitions}
    for event in events:
        state = transitions[state][event]
        visits[state] += 1
    return _input(
        'Trace this finite state machine. For each event use transitions[current_state][event] '
        'to replace the state, then increment that NEW state\'s visit count. Do not count the initial '
        'state before any event. Return an object with "state" (final string) and "visits" '
        '(all state names mapped to integer counts).',
        {'initial': initial, 'transitions': transitions, 'events': events}), {'state': state, 'visits': visits}


def dedup_repair(rng, level):
    values = [rng.randint(1, 5) for _ in range(3 + level * 3)]
    # Force both an adjacent repetition and a later non-adjacent repetition.
    values[:4] = [1, 1, 2, 1]
    correct = 'not out or out[-1] != x'
    choices = [correct, 'x not in out', 'out and out[-1] != x', 'not out or out[-1] == x']
    rng.shuffle(choices)
    output = []
    for value in values:
        if not output or value != output[-1]:
            output.append(value)
    return _input(
        'Repair adjacent-run compression for every input list: start out=[]; for each x, '
        'append x if CONDITION. Preserve later repetitions separated by other values. '
        'Choose a condition and return an object with "option" (letter) and "output" '
        '(compressed given values).',
        {'choices': dict(zip('ABCD', choices)), 'values': values}), {
            'option': 'ABCD'[choices.index(correct)], 'output': output}


def insertion_repair(rng, level):
    values = sorted(rng.randint(0, 8) for _ in range(5 + level * 3))
    queries = [min(values) - 1, max(values) + 1, rng.choice(values)] + [rng.randint(0, 8) for _ in range(level)]
    choices = ['values[mid] < target', 'values[mid] <= target', 'values[mid] > target', 'values[mid] >= target']
    correct = choices[0]
    rng.shuffle(choices)
    return _input(
        'Repair lower-bound binary search. lo=0; hi=len(values); while lo<hi: mid=(lo+hi)//2; '
        'if CONDITION: lo=mid+1; else: hi=mid. Return lo, the first index whose value is >=target, '
        'or len(values) if none. Choose the condition that works for every sorted input, including '
        'duplicates and empty lists. Return an object with "option" (letter) and "indices" '
        '(outputs for given queries).',
        {'choices': dict(zip('ABCD', choices)), 'values': values, 'queries': queries}), {
            'option': 'ABCD'[choices.index(correct)],
            'indices': [sum(value < target for value in values) for target in queries]}


def ledger(rng, level):
    accounts = list('ABCD')[:1 + level]
    initial = {name: rng.randint(0, 20) for name in accounts}
    entries = [[index, rng.choice(accounts), rng.randint(-7, 9), rng.choice(['posted', 'void'])]
               for index in range(4 + level * 3)]
    entries.append(entries[0].copy())
    rng.shuffle(entries)
    balances = initial.copy()
    seen = set()
    accepted = []
    for entry_id, account, amount, status in entries:
        if status == 'posted' and entry_id not in seen:
            seen.add(entry_id)
            balances[account] += amount
            accepted.append(entry_id)
    return _input(
        'Reconcile this ledger. Ignore void entries. Apply each posted ID only once, using its '
        'first posted occurrence; duplicates have identical data. Start from initial balances. '
        'Return an object with "balances" (all accounts) and "ids" (accepted IDs sorted ascending).',
        {'initial': initial, 'entries': entries}), {'balances': balances, 'ids': sorted(accepted)}


def interval_records(rng, level):
    low = rng.randint(0, 10)
    high = low + rng.randint(2, 8)
    teams = list('ABC')[:level]
    records = [[index, rng.randint(low - 2, high + 2), rng.choice(list('ABC')), rng.randint(1, 9)]
               for index in range(4 + level * 4)]
    records.extend([[len(records), low, teams[0], 2], [len(records) + 1, high, teams[0], 3]])
    selected = [row for row in records if low <= row[1] < high and row[2] in teams]
    return _input(
        'Use the half-open time window [start,end), and only permitted teams. '
        'Records are [ID,time,team,amount]. Return an object with "ids" (selected IDs in input '
        'order) and "amount" (sum of selected amounts).',
        {'start': low, 'end': high, 'teams': teams, 'records': records}), {
            'ids': [row[0] for row in selected], 'amount': sum(row[3] for row in selected)}


def grouped_shape(rng, level):
    groups = list('ABC')[:level]
    rows = [[rng.choice(groups), rng.randint(1, 9)] for _ in range(3 + level * 3)]
    buckets = {group: [] for group in groups}
    for group, value in rows:
        buckets[group].append(value)
    return _input(
        'Group rows [group,value] by group. Return an object with exactly "groups", an array '
        'ordered by group name ascending. Each entry has exactly "key" (group name), "values" '
        '(all values ascending, duplicates preserved), and "count". Include only groups present.',
        {'rows': rows}), {'groups': [
            {'key': group, 'values': sorted(values), 'count': len(values)}
            for group, values in sorted(buckets.items()) if values]}


def sparse_shape(rng, level):
    height, width = level + 1, level + 2
    cells = rng.sample(range(height * width), 2 + level)
    cells.sort(reverse=True)
    entries = [[index // width, index % width, rng.choice([-2, -1, 1, 2])] for index in cells]
    columns = []
    for column in range(width):
        nonzero = sorted(([row, value] for row, col, value in entries if col == column))
        columns.append({'column': column, 'cells': [{'row': row, 'value': value} for row, value in nonzero]})
    return _input(
        'Reshape unique sparse entries [row,column,value] into columns. Coordinates are zero-based. '
        'Return an object with exactly "columns", including every column index from 0 to width-1 '
        'ascending, even empty columns. Each column has exactly "column" and "cells"; each cell '
        'has exactly "row" and "value". Order cells by row ascending. Do not insert zero cells.',
        {'height': height, 'width': width, 'entries': entries}), {'columns': columns}
