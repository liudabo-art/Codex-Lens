"""Bounded model IDs from configuration/API; no hard-coded availability claims."""
import json
import re

from .protocol import MODEL_PATTERN


def model_choices(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = re.split(r'[\s,;]+', value[:32768])
    if isinstance(value, dict):
        value = value.get('data', value.get('models', []))
    if not isinstance(value, list):
        return []
    result = []
    for row in value[:1000]:
        item = row.get('id', row.get('slug', row.get('model'))) if isinstance(row, dict) else row
        if isinstance(item, str) and MODEL_PATTERN.fullmatch(item) and item not in result:
            result.append(item)
    return result


def display_name(value):
    if value is None:
        return '未命名测试'
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 60 or any(ord(c)<32 for c in value):
        raise ValueError('invalid_display_name')
    return value.strip()
