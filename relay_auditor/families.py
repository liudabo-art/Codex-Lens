"""A declared family selects tests. It is never an identification result."""
from dataclasses import dataclass, replace
import hashlib


@dataclass(frozen=True)
class TestProfile:
    tasks: tuple


PROFILES = {
    'gpt': TestProfile(('code_branch', 'constraints', 'repair_edges', 'structured', 'tool_args')),
    'deepseek': TestProfile(('constraints_multi', 'code', 'constraints_multi', 'repair', 'structured')),
    'claude': TestProfile(('document', 'structured', 'code', 'document', 'tool_args')),
    'gemini': TestProfile(('document', 'constraints', 'structured', 'code', 'tool_args')),
}
GENERIC = TestProfile(('constraints', 'code', 'repair', 'structured', 'tool_args'))
PREFIXES = {
    'gpt': ('gpt-', 'codex', 'o1', 'o3', 'o4'),
    'deepseek': ('deepseek-',),
    'claude': ('claude-',),
    'gemini': ('gemini-',),
    'qwen': ('qwen',),
    'glm': ('glm-',),
    'kimi': ('kimi-', 'moonshot-'),
    'minimax': ('minimax-',),
    'grok': ('grok-',),
    'mistral': ('mistral-', 'codestral-', 'ministral-'),
    'llama': ('llama-',),
}
REFERENCE_FAMILY = {
    'chat': 'gpt', 'responses': 'gpt', 'deepseek': 'deepseek',
    'anthropic': 'claude', 'gemini': 'gemini',
}


def family_for(model):
    name = model.rsplit('/', 1)[-1].lower()
    if name == 'gpt5.6sol':
        return 'gpt'
    return next((family for family, prefixes in PREFIXES.items() if name.startswith(prefixes)), 'unknown')


def matching_reference(monitor):
    target, reference = monitor.target, monitor.reference
    if reference_issue(monitor):
        return False
    if monitor.reference_preset:
        from .official import compatible_protocols
        return bool(
            target.role == 'relay' and reference
            and monitor.reference_declared_model == target.model
            and reference.official_preset == monitor.reference_preset
            and compatible_protocols(monitor.reference_preset, target.protocol, reference.protocol, reference.model)
        )
    return bool(
        target.role == 'relay' and reference
        and target.model == reference.model
        and target.protocol == reference.protocol
        and family_for(target.model) in ('unknown', REFERENCE_FAMILY[reference.protocol.wire_api])
    )


def usable_reference(monitor):
    return monitor.reference if matching_reference(monitor) else None


def reference_issue(monitor):
    if monitor.reference_error:
        return monitor.reference_error
    if monitor.reference and monitor.reference.protocol.wire_api == 'deepseek':
        from .official import retired_model
        if retired_model('deepseek', monitor.reference.model):
            return 'reference_model_retired'
    return None


def reasoning_reference(monitor):
    reference = usable_reference(monitor)
    if reference and monitor.reference_preset:
        from .official import compatible_protocols
        for effort in ('low', 'high'):
            relay_protocol = replace(monitor.target.protocol, reasoning_effort=effort)
            official_protocol = replace(reference.protocol, reasoning_effort=effort)
            if not compatible_protocols(monitor.reference_preset, relay_protocol, official_protocol, reference.model):
                return None
    return reference


def reference_state(monitor):
    if monitor.target.role == 'official_api':
        return 'official_direct'
    if matching_reference(monitor):
        return monitor.reference_state or 'reference_matched'
    if reference_issue(monitor):
        return 'reference_unavailable'
    if monitor.reference_preset:
        if monitor.reference_declared_model != monitor.target.model:
            return 'reference_mismatch'
        return 'reference_mismatch' if monitor.reference else 'reference_key_required'
    return 'reference_mismatch' if monitor.reference else 'reference_missing'


def reference_identity(monitor):
    identity = monitor.target.protocol.identity
    if not monitor.reference_preset:
        return None if monitor.reference and not matching_reference(monitor) else identity
    reference = usable_reference(monitor)
    if reference:
        binding = (identity, monitor.reference_preset, reference.protocol.identity)
        return 'synthetic-v1-' + hashlib.sha256('|'.join(binding).encode()).hexdigest()[:16]
    return None
