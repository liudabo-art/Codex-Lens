"""Provenance-first integration contract; current login is never historical evidence."""
import math


def group_usage(rows):
    fields = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')
    def empty():
        return {**dict.fromkeys(fields, 0), 'record_count': 0}
    groups = {name: empty() for name in ('official_login', 'relay', 'official_api', 'unknown', 'probe', 'reference')}
    providers = {}
    invalid_records = 0
    for row in rows:
        if not isinstance(row, dict) or 'input_tokens' not in row or 'output_tokens' not in row:
            invalid_records += 1
            continue
        values = {}
        for key in fields[:-1]:
            value = row.get(key, 0)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                values = None
                break
            values[key] = int(value)
        if values is None:
            invalid_records += 1
            continue
        values['total_tokens'] = values['input_tokens'] + values['output_tokens']
        evidence = row.get('source_evidence') or {}
        destination = evidence.get('destination')
        if row.get('purpose') in ('probe', 'reference'):
            kind = row['purpose']
        elif evidence.get('scope') != 'request':
            kind = 'unknown'
        elif destination == 'relay' and evidence.get('provider'):
            kind = 'relay'
        elif destination == 'official' and evidence.get('auth_mode') == 'chatgpt':
            kind = 'official_login'
        elif destination == 'official' and evidence.get('auth_mode') == 'api_key':
            kind = 'official_api'
        else:
            kind = 'unknown'
        targets = [groups[kind]]
        if kind == 'relay':
            # Original provider key lives only in this invocation; no alias map is saved.
            key = evidence['provider']
            if key not in providers:
                providers[key] = {'source_alias': f'relay-{len(providers)+1}', **empty()}
            targets.append(providers[key])
        for target in targets:
            target['record_count'] += 1
            for key, value in values.items():
                target[key] += value
    return {**groups, 'relay_providers': list(providers.values()), 'invalid_records': invalid_records,
            'source_attribution': 'request_evidence_required'}
