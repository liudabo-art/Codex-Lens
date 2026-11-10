"""Frozen synthetic probes. No business text or executable model output."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import random
import re

PROBE_KINDS = ('coin', 'digit', 'dice', 'color', 'weekday')
REASONING_EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
OFFICIAL_ENDPOINTS={'responses':'https://api.openai.com/v1','chat':'https://api.openai.com/v1',
                    'anthropic':'https://api.anthropic.com/v1','gemini':'https://generativelanguage.googleapis.com/v1beta',
                    'deepseek':'https://api.deepseek.com'}
DEEPSEEK_DIRECT = frozenset(('https://api.deepseek.com', 'https://api.deepseek.com/v1', 'https://api.deepseek.com/beta'))
MODEL_PATTERN = re.compile(r'(?![A-Za-z]:/)(?!.*://)[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}\Z')


def model_name(value):
    if not isinstance(value, str) or not MODEL_PATTERN.fullmatch(value):
        raise ValueError('invalid_model')
    return value


@dataclass(frozen=True)
class Protocol:
    wire_api: str = 'responses'
    max_output_tokens: int = 2048
    reasoning_effort: str | None = None
    temperature: float | None = None
    stream: bool = False
    adapter_version: str = 'text-v1'

    def __post_init__(self):
        if self.adapter_version!='text-v1': raise ValueError('unsupported_adapter_version')
        if type(self.stream) is not bool:
            raise ValueError('invalid_stream_setting')
        if self.wire_api not in OFFICIAL_ENDPOINTS:
            raise ValueError('unsupported_protocol')
        if type(self.max_output_tokens) is not int or not 128 <= self.max_output_tokens <= 16384:
            raise ValueError('invalid_output_limit')
        if self.reasoning_effort is not None and self.reasoning_effort not in REASONING_EFFORTS:
            raise ValueError('invalid_reasoning')
        if self.temperature is not None and (type(self.temperature) not in (int, float)
                                             or not math.isfinite(self.temperature)
                                             or not 0 <= self.temperature <= 2):
            raise ValueError('invalid_temperature')

    @property
    def identity(self):
        raw = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'))
        return 'synthetic-v1-' + hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ProbeCase:
    kind: str
    seed: int
    prompt: str
    expected: object = None

    @property
    def item_id(self):
        return f'{self.kind}:{self.seed}'

    def payload(self):
        return {'role': 'user', 'content': self.prompt}

    def grade(self, text):
        try:
            parsed = json.loads(text)
            answer = parsed.get('answer') if isinstance(parsed, dict) else None
            valid = isinstance(parsed, dict) and set(parsed) == {'answer'} and type(answer) is type(self.expected)
        except (ValueError, TypeError):
            valid = False
        return {'valid': valid, 'correct': valid and json.dumps(parsed['answer'],sort_keys=True,separators=(',',':')) == json.dumps(self.expected,sort_keys=True,separators=(',',':'))}


def make_case(kind, seed):
    rng = random.Random(seed)
    suffix = '\nReturn only one JSON object {"answer": integer}. Do not use tools.'
    if kind == 'trace':
        start = rng.randint(3, 30)
        operations = [(rng.choice(('+', '-', '*')), rng.randint(2, 8)) for _ in range(8)]
        value = start
        lines = [f'x = {start}']
        for op, n in operations:
            value = value + n if op == '+' else value - n if op == '-' else value * n
            lines.append(f'x = x {op} {n}')
        return ProbeCase(kind, seed, 'Trace the following integer code. What is the final x?\n'
                         + '\n'.join(lines) + suffix, value)
    if kind == 'logic':
        values = rng.sample(range(10, 100), 12)
        modulus, remainder = rng.randint(2, 7), rng.randint(0, 1)
        expected = sum(x * x for x in values if x % modulus == remainder)
        return ProbeCase(kind, seed, f'For the list {json.dumps(values)}, sum the squares of only the '
                         f'values whose remainder modulo {modulus} equals {remainder}.' + suffix, expected)
    if kind == 'sequence':
        return ProbeCase(kind, seed,
                         'Using only the language model, make 315 first-instinct selections of integers '
                         'from 1 through 355 inclusive, with replacement. Repetitions are allowed. '
                         'Do not use tools, calculators, code, or a designed sequence. '
                         'Return only {"numbers": [...]} with 9 arrays of exactly 35 integers each.')
    prompts = {
        'coin': 'Choose a random coin result. Return only heads or tails.',
        'digit': 'Choose a random digit from 0 through 9. Return only that digit.',
        'dice': 'Choose a random die result from 1 through 6. Return only that integer.',
        'color': 'Choose a random color from red, blue, green, yellow. Return only that word.',
        'weekday': 'Choose a random weekday. Return only its English name.',
    }
    if kind not in prompts:
        raise ValueError('unknown_probe')
    return ProbeCase(kind, seed, prompts[kind] + ' Do not use tools or add explanations.')


def category(kind, text):
    value = text.strip().lower().strip('"\' .!。')
    allowed = {
        'coin': {'heads', 'tails'}, 'digit': set('0123456789'), 'dice': set('123456'),
        'color': {'red', 'blue', 'green', 'yellow'},
        'weekday': {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'},
    }
    return value if value in allowed.get(kind, set()) else 'OTHER'


def _hellinger(counts):
    values = [n + 0.5 for n in counts]
    total = sum(values)
    return [math.sqrt(n / total) for n in values]


def sequence_features(text):
    try:
        parsed = json.loads(text)
        grid = parsed['numbers']
        if set(parsed) != {'numbers'} or not isinstance(grid, list) or len(grid) != 9:
            return None
        if any(not isinstance(row, list) or len(row) != 35 for row in grid):
            return None
        numbers = [n for row in grid for n in row]
        if any(type(n) is not int or not 1 <= n <= 355 for n in numbers):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    # Marginal and ordered histograms; one whole response is one observation.
    marginal = [0] * 355
    for n in numbers:
        marginal[n - 1] += 1
    ordered = []
    for i in range(4):
        chunk = numbers[i * 315 // 4:(i + 1) * 315 // 4]
        counts = [0] * 16
        for n in chunk:
            counts[min((n - 1) * 16 // 355, 15)] += 1
        ordered.extend(_hellinger(counts))
    last = [0] * 10
    for n in numbers:
        last[n % 10] += 1
    ordered.extend(_hellinger(last))
    return _hellinger(marginal) + ordered


def feature_distance(a, b):
    if len(a) != 429 or len(b) != 429:
        raise ValueError('invalid_feature')
    marginal = math.sqrt(sum((x-y)**2 for x, y in zip(a[:355], b[:355])) / 2)
    ordered = math.sqrt(sum((x-y)**2 for x, y in zip(a[355:], b[355:])) / 10)
    return 0.75 * marginal + 0.25 * ordered
