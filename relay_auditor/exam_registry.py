"""Immutable paper contracts; a family never inherits another family's exam."""
from dataclasses import asdict, dataclass
import hashlib
import json
from types import MappingProxyType


EXAM_TASKS = ('exam_reasoning', 'exam_code', 'exam_repair', 'exam_information', 'exam_structure')
EXAM_SIZES = (120, 180)


@dataclass(frozen=True)
class ExamSpec:
    family: str
    version: str
    sizes: tuple = EXAM_SIZES
    task_kinds: tuple = EXAM_TASKS
    max_prompt_bytes: int = 4096
    max_retries_per_item: int = 2

    @property
    def paper_spec_id(self):
        """Bind every frozen public field without mutable approval metadata."""
        body = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return 'exam-spec-v1-' + hashlib.sha256(body.encode('utf-8')).hexdigest()

    def retry_requests_per_side(self, samples):
        if type(samples) is not int or samples not in self.sizes:
            raise ValueError('invalid_exam_paper')
        return samples // 5


_DEFAULTS = MappingProxyType({
    'gpt': ExamSpec('gpt', 'exam-v2'),
    'deepseek': ExamSpec('deepseek', 'exam-v2'),
    'claude': ExamSpec('claude', 'claude-exam-v1', max_prompt_bytes=8192),
    'gemini': ExamSpec('gemini', 'gemini-exam-v1', max_prompt_bytes=8192),
})


def get_exam_spec(family, suite_version=None):
    """Resolve an exact supported family/version pair, never silently substitute."""
    if not isinstance(family, str) or family not in _DEFAULTS:
        raise ValueError('invalid_exam_paper')
    spec = _DEFAULTS[family]
    if suite_version is not None and suite_version != spec.version:
        raise ValueError('invalid_exam_paper')
    return spec


def exam_suite_versions():
    return tuple(dict.fromkeys(spec.version for spec in _DEFAULTS.values()))


def is_exam_suite(version):
    return isinstance(version, str) and version in exam_suite_versions()
