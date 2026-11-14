"""Reviewed four-family text parameters, never inferred from a family prefix.

This is a local serialization policy, not a model availability or identity claim.
None always means leave the setting to the service; it never means effort=none.
Unknown scoped models retain default requests but no unverified explicit effort.
Other providers retain their existing adapters and compatibility policies.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .families import family_for


CAPABILITIES_VERSION = 'four-family-text-parameters-2026-11-14-v1'


@dataclass(frozen=True)
class _Parameters:
    wires: tuple[str, ...]
    efforts: tuple[str, ...]
    default_effort: str | None
    temperature: str
    thinking: str | None = None
    effort_aliases: tuple[str, ...] = ()


_LOW_HIGH = ('low', 'medium', 'high')
_XHIGH = (*_LOW_HIGH, 'xhigh')
_MAX = (*_XHIGH, 'max')
_OPENAI_WIRES = ('responses', 'chat')
_models = {}


def _add(ids, efforts, default='medium', temperature='none_only', *, wires=_OPENAI_WIRES,
         thinking=None, effort_aliases=()):
    entry = _Parameters(wires, efforts, default, temperature, thinking, effort_aliases)
    for model in ids:
        _models[model] = entry


# Exact IDs/snapshots and endpoint support were reviewed on each model page:
# https://developers.openai.com/api/docs/models/<model-id>
# GPT-5 mini/nano settings are also explicitly listed in:
# https://developers.openai.com/api/docs/guides/latest-model/gpt-5
# Sampling restrictions for GPT-5/5.1/5.2/5.4:
# https://developers.openai.com/api/docs/guides/latest-model/gpt-5.2#GPT-5.2-parameter-compatibility
# https://developers.openai.com/api/docs/guides/latest-model/gpt-5.4#GPT-5.4-parameter-compatibility
_add(('gpt-5', 'gpt-5-2025-08-07', 'gpt-5-mini', 'gpt-5-mini-2025-08-07',
      'gpt-5-nano', 'gpt-5-nano-2025-08-07'), ('minimal', *_LOW_HIGH), temperature='unsupported')
_add(('gpt-5.1', 'gpt-5.1-2025-11-13'), ('none', *_LOW_HIGH), default='none')
_add(('gpt-5.2', 'gpt-5.2-2025-12-11', 'gpt-5.4', 'gpt-5.4-2026-03-05',
      'gpt-5.4-mini', 'gpt-5.4-mini-2026-03-17', 'gpt-5.4-nano', 'gpt-5.4-nano-2026-03-17'),
     ('none', *_XHIGH), default='none')
_add(('gpt-5.5', 'gpt-5.5-2026-04-23'), ('none', *_XHIGH))
_add(('gpt-5.6-sol', 'gpt-5.6', 'gpt5.6sol', 'gpt-5.6-terra', 'gpt-5.6-luna',
      'gpt-6.1-terra', 'gpt-6-sol', 'gpt-6-luna'), ('none', *_MAX))
_add(('gpt-6-astra', 'gpt-6.1-sol'), _MAX, temperature='unsupported')
_add(('gpt-5.2-codex', 'gpt-5.3-codex'), _XHIGH, temperature='unsupported', wires=('responses',))
_add(('gpt-5.2-pro', 'gpt-5.2-pro-2025-12-11', 'gpt-5.4-pro', 'gpt-5.4-pro-2026-03-05',
      'gpt-5.5-pro', 'gpt-5.5-pro-2026-04-23'), ('medium', 'high', 'xhigh'),
     temperature='unsupported', wires=('responses',))

# These models do not expose reasoning effort. Explicit effort=none is not a
# substitute for leaving an absent parameter out of the request.
_add(('gpt-4.1', 'gpt-4.1-2025-04-14', 'gpt-4o', 'gpt-4o-2024-08-06', 'gpt-4o-2024-11-20',
      'gpt-4o-2024-05-13'), (), default=None, temperature='free')

# https://platform.claude.com/docs/en/build-with-claude/thinking#configuring-thinking
# https://platform.claude.com/docs/en/build-with-claude/effort#effort-levels
# https://platform.claude.com/docs/en/build-with-claude/thinking#sampling-parameters
# Native requests retain anthropic-version 2023-06-01. Later API versions have
# different sampling rules and must be reviewed before that header is changed.
_add(('claude-sonnet-4-5', 'claude-sonnet-4-5-20250929', 'claude-haiku-4-5', 'claude-haiku-4-5-20251001'),
     ('none',), default=None, temperature='off_only', wires=('anthropic',), thinking='manual')
_add(('claude-opus-4-5', 'claude-opus-4-5-20251101'), ('none', *_LOW_HIGH), default=None,
     temperature='off_only', wires=('anthropic',), thinking='manual')
_add(('claude-opus-4-6', 'claude-sonnet-4-6'), ('none', *_LOW_HIGH, 'max'), default=None,
     temperature='off_only', wires=('anthropic',), thinking='adaptive')
_add(('claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-5-5'),
     ('none', *_MAX), default=None, temperature='fixed_one', wires=('anthropic',), thinking='adaptive')
_add(('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-5', 'claude-fable-5-1', 'claude-fable-5-2',
      'claude-mythos-5', 'claude-mythos-5-1', 'claude-mythos-5-2'),
     _MAX, default=None, temperature='fixed_one', wires=('anthropic',), thinking='adaptive')

# https://api-docs.deepseek.com/quick_start/pricing/
# https://api-docs.deepseek.com/api/create-chat-completion/
# https://api-docs.deepseek.com/guides/thinking_mode/
# Canonical efforts are offered for new selections. Documented compatibility
# aliases are accepted and sent unchanged: minimal -> low; medium/xhigh -> high.
# This mapping belongs to the provider; this application never rewrites it.
# Temperature has no effect with thinking on, including the default high mode.
_add(('deepseek-flash', 'deepseek-v4-pro'), ('none', 'low', 'high', 'max'), default='high',
     wires=('deepseek', 'chat'), thinking='deepseek', effort_aliases=('minimal', 'medium', 'xhigh'))

# Native generateContent policy (NOT the Interactions API thinking-level table):
# https://aistudio.google.com/docs/thinking?generate-content=true
# https://aistudio.google.com/api-reference/generate-content#ThinkingConfig
# https://aistudio.google.com/docs/whats-new-gemini-3.6?generate-content=true#api-changes-and-parameter-updates
# Gemini 2.5 has numeric thinkingBudget, not qualitative thinkingLevel. The
# existing effort selector can express only its documented disabled value (0).
# Pro cannot disable thinking. No low/medium/high -> token-budget mapping exists.
_add(('gemini-2.5-pro',), (), default=None, temperature='free', wires=('gemini',), thinking='budget')
_add(('gemini-2.5-flash', 'gemini-2.5-flash-lite'), ('none',), default=None,
     temperature='free', wires=('gemini',), thinking='budget')
_add(('gemini-3-pro-preview',), ('low', 'high'), default='high', temperature='free',
     wires=('gemini',), thinking='level')
_add(('gemini-3.1-pro-preview',), _LOW_HIGH, default='high', temperature='free',
     wires=('gemini',), thinking='level')
_add(('gemini-3-flash-preview', 'gemini-3.1-flash-lite'), ('minimal', *_LOW_HIGH),
     default=None, temperature='free', wires=('gemini',), thinking='level')
_add(('gemini-3.6-flash', 'gemini-3.5-flash-lite'), ('minimal', *_LOW_HIGH),
     default=None, temperature='unsupported', wires=('gemini',), thinking='level')
_add(('gemini-3.8-flash', 'gemini-4-carbon', 'gemini-4-argon'), _LOW_HIGH,
     default=None, temperature='unsupported', wires=('gemini',), thinking='level')
_add(('gemini-4-hydrogen',), _XHIGH, default='high', temperature='unsupported',
     wires=('gemini',), thinking='level')
# The native API resource form is an exact documented alias; no suffix/family
# matching is used. Include it in the public catalog for UI/backend agreement.
for _model, _entry in tuple(_models.items()):
    if _entry.wires == ('gemini',):
        _models['models/' + _model] = _entry

_MODELS = MappingProxyType(_models)
del _models


def allowed_reasoning_efforts(model, wire):
    """Reviewed explicit effort choices. The model-default choice is separate."""
    entry = _MODELS.get(model)
    return entry.efforts if entry and wire in entry.wires else ()


def reasoning_catalog():
    """Return an independent, JSON-ready copy of reviewed model/wire choices."""
    return {model: {wire: list(entry.efforts) for wire in entry.wires}
            for model, entry in _MODELS.items()}


def supports_parameters(model, protocol):
    """Check scoped parameters without mutation, networking, or fallback."""
    if family_for(model) not in ('gpt', 'claude', 'deepseek', 'gemini'):
        return True
    entry = _MODELS.get(model)
    effort, temperature = protocol.reasoning_effort, protocol.temperature
    if entry is None or protocol.wire_api not in entry.wires:
        # Keep unreviewed/default relay configurations usable. A known OpenAI
        # Responses-only model must not silently move to Chat Completions.
        if entry and family_for(model) == 'gpt':
            return False
        return effort is None and temperature is None
    if effort is not None and effort not in (*entry.efforts, *entry.effort_aliases):
        return False
    if temperature is None:
        return True
    if entry.temperature == 'free':
        return True
    if entry.temperature == 'fixed_one':
        return temperature == 1
    if entry.temperature == 'none_only':
        return (effort if effort is not None else entry.default_effort) == 'none'
    if entry.temperature == 'off_only':
        return temperature <= 1 and (entry.thinking == 'manual' or effort in (None, 'none'))
    return False


def anthropic_thinking_options(model, effort):
    """Serialize validated Claude settings without guessing a thinking budget."""
    if effort is None:
        return {}
    if effort not in allowed_reasoning_efforts(model, 'anthropic'):
        raise ValueError('unsupported_parameters')
    if effort == 'none':
        return {'thinking': {'type': 'disabled'}}
    result = {'output_config': {'effort': effort}}
    if _MODELS[model].thinking == 'adaptive':
        result['thinking'] = {'type': 'adaptive'}
    return result


def deepseek_thinking_options(model, effort):
    """Preserve provider-accepted efforts, including documented legacy aliases."""
    if effort is None:
        return {}
    entry = _MODELS.get(model)
    if entry is None or 'deepseek' not in entry.wires or effort not in (*entry.efforts, *entry.effort_aliases):
        raise ValueError('unsupported_parameters')
    if effort == 'none':
        return {'thinking': {'type': 'disabled'}}
    return {'thinking': {'type': 'enabled'}, 'reasoning_effort': effort}


def gemini_thinking_options(model, effort):
    """Serialize exact native thinking controls without estimating token budgets."""
    if effort is None:
        return {}
    if effort not in allowed_reasoning_efforts(model, 'gemini'):
        raise ValueError('unsupported_parameters')
    if _MODELS[model].thinking == 'budget':
        return {'thinkingConfig': {'thinkingBudget': 0}}
    return {'thinkingConfig': {'thinkingLevel': effort.upper()}}
