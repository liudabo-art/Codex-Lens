"""Bounded deterministic JSON scoring; response text never leaves this module."""
import json
import math
import re


MAX_ANSWER_BYTES = 65536
MAX_JSON_DEPTH = 64
MAX_JSON_CANDIDATES = 8
_SCALAR = re.compile(r'(?<![\w])(?:"(?:[^"\\]|\\.)*"|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?![\w])')
_SCALAR_SEQUENCE = re.compile(f'(?:{_SCALAR.pattern})(?:\\s+(?:{_SCALAR.pattern}))*')
SAFE_TEMPLATES = frozenset((
    'constraints', 'constraints_multi', 'code', 'code_branch', 'repair', 'repair_edges',
    'structured', 'tool_args', 'document', 'dependency', 'stack', 'slice_repair',
    'tier_repair', 'join', 'policy', 'nested', 'tool_plan', 'shortest_path', 'schedule',
    'registers', 'state_machine', 'dedup_repair', 'insertion_repair', 'ledger',
    'interval_records', 'grouped_shape', 'sparse_shape',
))
GRADING_ISSUES = frozenset((
    'ambiguous_answer', 'duplicate_keys', 'missing_answer', 'missing_fields',
    'unexpected_fields', 'answer_type', 'invalid_json', 'nonfinite_number',
    'answer_too_large', 'answer_too_deep', 'too_many_candidates',
))


class _FormatError(ValueError):
    pass


def _unique_keys(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _FormatError('duplicate_keys')
    return result


def _constant(_value):
    raise _FormatError('nonfinite_number')


def _check_depth(text):
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise _FormatError('answer_too_deep')
        elif char in '}]':
            depth -= 1


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise _FormatError('nonfinite_number')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _validate(value, examples):
    compatible = [example for example in examples if type(value) is type(example)]
    if not compatible:
        raise _FormatError('answer_type')
    if isinstance(value, dict):
        matching = [example for example in compatible if set(example) == set(value)]
        if not matching and set(compatible[0]) - set(value):
            raise _FormatError('missing_fields')
        if not matching:
            raise _FormatError('unexpected_fields')
        for key, item in value.items():
            _validate(item, [example[key] for example in matching])
    elif isinstance(value, list):
        # Arrays carry a repeated value schema; length and order remain answer content.
        elements = [item for example in compatible for item in example]
        if elements:
            for item in value:
                _validate(item, elements)


def grade_answer(case, text):
    """Score a sole JSON value, or a unique complete object/array embedded in prose.

    Candidate extraction never consults the expected answer. Multiple roots, including
    identical repeats, are ambiguous. Malformed roots and duplicate keys fail closed.
    """
    try:
        if not isinstance(text, str):
            raise _FormatError('invalid_json')
        if len(text) > MAX_ANSWER_BYTES or len(text.encode('utf-8')) > MAX_ANSWER_BYTES:
            raise _FormatError('answer_too_large')
        stripped = text.strip()
        decoder = json.JSONDecoder(object_pairs_hook=_unique_keys, parse_constant=_constant)
        _check_depth(stripped)
        try:
            parsed = decoder.decode(stripped)
            bare = True
        except json.JSONDecodeError:
            bare = False
            candidates = []
            outside = []
            last_end = 0
            position = 0
            while position < len(stripped):
                if stripped[position] not in '{[':
                    position += 1
                    continue
                try:
                    value, end = decoder.raw_decode(stripped, position)
                except json.JSONDecodeError:
                    raise _FormatError('invalid_json') from None
                candidates.append(value)
                outside.append(stripped[last_end:position])
                if len(candidates) > MAX_JSON_CANDIDATES:
                    raise _FormatError('too_many_candidates')
                position = end
                last_end = end
            outside.append(stripped[last_end:])
            if not candidates:
                raise _FormatError('missing_answer')
            if len(candidates) != 1:
                raise _FormatError('ambiguous_answer')
            # Bare scalars on their own line are additional explicit JSON roots. Numerals
            # inside prose are not inferred as answers (for example "question 1").
            if any(_SCALAR_SEQUENCE.fullmatch(line.strip()) for part in outside for line in part.splitlines()):
                raise _FormatError('ambiguous_answer')
            parsed = candidates[0]
        wrapped = isinstance(parsed, dict) and 'answer' in parsed
        answer = parsed['answer'] if wrapped else parsed
        _finite(parsed)
        _validate(answer, [case.expected])
        correct = json.dumps(answer, sort_keys=True, allow_nan=False, separators=(',', ':')) == json.dumps(
            case.expected, sort_keys=True, allow_nan=False, separators=(',', ':'))
        state = 'valid' if bare and wrapped and len(parsed) == 1 else 'recovered_format'
        return {'correct': correct, 'format_state': state,
                'error_code': None if state == 'valid' else state, 'grading_issue': None}
    except _FormatError as error:
        issue = str(error)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        issue = 'invalid_json'
    return {'correct': None, 'format_state': 'answer_format',
            'error_code': 'answer_format', 'grading_issue': issue}


def item_result(case, difficulty, question, source):
    """Initialize anonymous fixed-schema metadata, including unstarted slots."""
    return {'question_number': question, 'task_kind': case.kind,
            'template': getattr(case, 'variant', '') or case.kind,
            'difficulty': difficulty, 'seed': case.seed, 'source_kind': source,
            'correct': None, 'format_state': 'answer_format', 'attempts': 0,
            'error_code': None, 'grading_issue': None}
