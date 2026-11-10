"""Fixed official text API origins and exact, provider-scoped model matching."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from .families import family_for
from .models import model_choices
from .protocol import model_name


CATALOG_VERSION = '2026-11-05'
MAX_MODEL_PAGES = 8


@dataclass(frozen=True)
class Preset:
    label: str
    family: str
    base_url: str
    wires: tuple[str, ...]
    discovery_path: str | None = '/models'
    catalog: tuple[str, ...] = ()
    chat_limit: str = 'max_completion_tokens'
    stream_usage: bool = True


# Beijing/Virginia model discovery requires a workspace ID. These entries use the
# documented text catalog. Availability for a particular key is tested by generation.
# https://www.alibabacloud.com/help/en/model-studio/models
# https://docs.modelstudio.console.alibabacloud.com/en/model-studio/list-models
_QWEN = ('qwen3.8-max', 'qwen3.8-flash', 'qwen3.7-max', 'qwen3.7-plus',
         'qwen3.6-plus', 'qwen3.6-flash', 'qwen3.5-plus', 'qwen3.5-flash',
         'qwen-max', 'qwen-plus', 'qwen-flash', 'qwen-turbo', 'qwen3-coder-plus', 'qwen3-coder-flash')

# https://docs.bigmodel.cn/api-reference/模型-api/对话补全
# https://docs.z.ai/api-reference/llm/chat-completion
_GLM_INTL = ('glm-5.3', 'glm-5.2', 'glm-5.1', 'glm-5', 'glm-4.7', 'glm-4.6')
_GLM_CN = (*_GLM_INTL, 'glm-5-turbo', 'glm-4.7-flash', 'glm-4.7-flashx', 'glm-4.5-air',
           'glm-4.5-airx', 'glm-4.5-flash', 'glm-4-flash-250414', 'glm-4-flashx-250414')

# https://platform.minimax.io/docs/api-reference/text-openai-api
# https://platform.minimax.cn/docs/api-reference/text-openai-api
_MINIMAX = ('MiniMax-M3.1-Flash', 'MiniMax-M3')


PRESETS = MappingProxyType({
    'openai': Preset('OpenAI', 'gpt', 'https://api.openai.com/v1', ('responses', 'chat')),
    'anthropic': Preset('Anthropic（Claude）', 'claude', 'https://api.anthropic.com/v1', ('anthropic',)),
    'google': Preset('Google（Gemini）', 'gemini', 'https://generativelanguage.googleapis.com/v1beta', ('gemini',)),
    'deepseek': Preset('DeepSeek', 'deepseek', 'https://api.deepseek.com', ('deepseek',)),
    'qwen-beijing': Preset('Qwen 百炼北京', 'qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', ('chat',),
                          None, _QWEN, 'max_tokens'),
    'qwen-singapore': Preset('Qwen 百炼新加坡', 'qwen', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', ('chat',),
                             '/api/v1/models', chat_limit='max_tokens'),
    'qwen-virginia': Preset('Qwen 百炼美国弗吉尼亚', 'qwen', 'https://dashscope-us.aliyuncs.com/compatible-mode/v1', ('chat',),
                           None, _QWEN, 'max_tokens'),
    'qwen-hongkong': Preset('Qwen 百炼中国香港', 'qwen', 'https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1', ('chat',),
                            '/api/v1/models', chat_limit='max_tokens'),
    'glm-cn': Preset('GLM 中国站', 'glm', 'https://open.bigmodel.cn/api/paas/v4', ('chat',), None, _GLM_CN, 'max_tokens', False),
    'glm-intl': Preset('GLM 国际站', 'glm', 'https://api.z.ai/api/paas/v4', ('chat',), None, _GLM_INTL, 'max_tokens', False),
    'kimi-cn': Preset('Kimi 中国站', 'kimi', 'https://api.moonshot.cn/v1', ('chat',)),
    'kimi-intl': Preset('Kimi 国际站', 'kimi', 'https://api.moonshot.ai/v1', ('chat',)),
    'minimax-cn': Preset('MiniMax 中国站', 'minimax', 'https://api.minimax.cn/v1', ('chat',), None, _MINIMAX),
    'minimax-intl': Preset('MiniMax 国际站', 'minimax', 'https://api.minimax.io/v1', ('chat',), None, _MINIMAX),
    'xai': Preset('xAI（Grok）', 'grok', 'https://api.x.ai/v1', ('responses', 'chat'), '/language-models',
                  chat_limit='max_tokens', stream_usage=False),
    'mistral': Preset('Mistral', 'mistral', 'https://api.mistral.ai/v1', ('chat',), chat_limit='max_tokens', stream_usage=False),
})

_ALIASES = {
    # https://developers.openai.com/api/docs/models/gpt-5.6-sol
    'openai': {'gpt5.6sol': 'gpt-5.6-sol', 'gpt-5.6': 'gpt-5.6-sol'},
    'minimax-cn': {model.lower(): model for model in _MINIMAX},
    'minimax-intl': {model.lower(): model for model in _MINIMAX},
}

_MISTRAL_PREFIXES = ('devstral-', 'magistral-', 'open-mistral-', 'open-mixtral-', 'pixtral-', 'mathstral-')
_NON_TEXT_PREFIXES = ('gpt-image-', 'gpt-realtime-', 'gpt-oss-', 'grok-imagine-', 'grok-2-image')
# https://api-docs.deepseek.com/quick_start/pricing/
_DEEPSEEK_RETIRED = ('deepseek-v4-flash', 'deepseek-v4-flash-vision-exp')


def _preset(preset_id):
    if not isinstance(preset_id, str) or preset_id not in PRESETS:
        raise ValueError('invalid_reference_preset')
    return PRESETS[preset_id]


def retired_model(preset_id, model):
    return preset_id == 'deepseek' and model in _DEEPSEEK_RETIRED


def official_model(preset_id, declared_model):
    preset = _preset(preset_id)
    try:
        candidate = model_name(declared_model)
    except ValueError:
        raise ValueError('reference_model_mismatch') from None
    if preset_id == 'google':
        candidate = candidate.removeprefix('models/')
    candidate = _ALIASES.get(preset_id, {}).get(candidate, candidate)
    family = family_for(candidate)
    if family == 'unknown' and candidate.startswith(_MISTRAL_PREFIXES):
        family = 'mistral'
    if '/' not in candidate and family not in ('unknown', preset.family):
        raise ValueError('reference_provider_mismatch')
    if retired_model(preset_id, candidate):
        raise ValueError('reference_model_retired')
    if ('/' in candidate or family != preset.family or candidate.lower().startswith(_NON_TEXT_PREFIXES)
            or preset.discovery_path is None and candidate not in preset.catalog):
        raise ValueError('reference_model_mismatch')
    return candidate


def restore_reference(preset_id, key, model, protocol):
    from .transport import Target

    return Target(_preset(preset_id).base_url, key, model, protocol, role='reference', official_preset=preset_id)


def reference_target(preset_id, relay_target, key, model):
    preset = _preset(preset_id)
    wire = relay_target.protocol.wire_api
    protocol = replace(relay_target.protocol, wire_api=wire if wire in preset.wires else preset.wires[0])
    return restore_reference(preset_id, key, model, protocol)


def _supports_parameters(preset, protocol, model):
    effort = protocol.reasoning_effort
    temperature = protocol.temperature
    if preset.family == 'gpt':
        if model == 'gpt-5.6-sol' and (effort == 'minimal' or temperature is not None and effort != 'none'):
            return False
        return temperature is None or effort in (None, 'none')
    if preset.family == 'claude':
        return (effort in (None, 'none', 'low', 'medium', 'high', 'max')
                and (temperature is None or temperature <= 1 and effort in (None, 'none')))
    if preset.family == 'gemini':
        return effort in (None, 'none', 'minimal', 'low', 'medium', 'high')
    if preset.family == 'deepseek':
        return effort in (None, 'none', 'low', 'high', 'max') and (temperature is None or effort == 'none')
    if preset.family == 'minimax':
        return temperature is None and (effort is None or model == 'MiniMax-M3.1-Flash'
                                        and effort in ('low', 'medium', 'high', 'xhigh', 'max'))
    if preset.family == 'glm':
        supported = {None}
        if model == 'glm-5.3':
            supported.update(('low', 'high', 'max'))
        elif model == 'glm-5.2':
            supported.update(('none', 'high', 'max'))
        return effort in supported and (temperature is None or temperature <= 1)
    if preset.family == 'kimi':
        # New Kimi models apply a fixed temperature according to thinking mode.
        supports_effort = model and model.startswith('kimi-k3') and effort in ('low', 'high', 'max')
        return (effort is None or supports_effort) and temperature is None
    if preset.family == 'grok':
        return effort is None and (temperature is None or temperature <= 1)
    return effort is None


def compatible_protocols(preset_id, relay_protocol, reference_protocol, model=None):
    preset = _preset(preset_id)
    wire = reference_protocol.wire_api
    if (wire not in preset.wires or replace(relay_protocol, wire_api=wire) != reference_protocol
            or not _supports_parameters(preset, reference_protocol, model)):
        return False
    if relay_protocol.wire_api == wire:
        return True
    # Only the common single-turn text settings are portable across these wire APIs.
    return (relay_protocol.wire_api == 'chat' and wire in ('anthropic', 'gemini', 'deepseek')
            and relay_protocol.reasoning_effort is None and relay_protocol.temperature is None)


def chat_options(target):
    """Official Chat Completions dialect, after the controller checks compatibility."""
    preset = _preset(target.official_preset)
    protocol = target.protocol
    limit = preset.chat_limit
    if preset.family == 'qwen' and target.model.startswith(
            ('qwen3.5-plus', 'qwen3.5-flash', 'qwen3.6-plus', 'qwen3.6-flash', 'qwen3.7-', 'qwen3.8-')):
        limit = 'max_completion_tokens'
    result = {limit: protocol.max_output_tokens}
    if protocol.stream and preset.stream_usage:
        result['stream_options'] = {'include_usage': True}
    if protocol.reasoning_effort is not None:
        result['reasoning_effort'] = protocol.reasoning_effort
    if preset.family == 'minimax':
        result['reasoning_split'] = True
    return result


def _with_unambiguous_aliases(rows):
    ids = model_choices(rows)
    aliases = {}
    for row in rows[:1000]:
        model = row.get('id')
        if model not in ids:
            continue
        for alias in model_choices(row.get('aliases')):
            aliases.setdefault(alias, set()).add(model)
    return ids + [alias for alias, candidates in aliases.items() if len(candidates) == 1]


def _model_page(preset_id, body):
    if preset_id == 'google':
        rows = body['models']
        if not isinstance(rows, list):
            raise ValueError('invalid_models')
        return [row['name'].removeprefix('models/') for row in rows if isinstance(row, dict)
                and 'generateContent' in row.get('supportedGenerationMethods', ())], body.get('nextPageToken')
    if preset_id.startswith('qwen-'):
        return body['output']['models'], None
    if preset_id in ('xai', 'mistral'):
        rows = body['models'] if preset_id == 'xai' else body if isinstance(body, list) else body['data']
        if not isinstance(rows, list):
            raise ValueError('invalid_models')
        rows = [row for row in rows if isinstance(row, dict) and not row.get('archived')]
        if preset_id == 'xai':
            rows = [row for row in rows if all('text' in row.get(name, ('text',))
                    for name in ('input_modalities', 'output_modalities'))]
        else:
            rows = [row for row in rows if (row.get('capabilities') or {}).get('completion_chat') is not False]
        return _with_unambiguous_aliases(rows), None
    rows = body['data']
    return rows, body['last_id'] if preset_id == 'anthropic' and body.get('has_more') else None


def list_models(target, opener):
    from .adapters import headers as native_headers, read
    from .transport import EndpointError

    preset_id = target.official_preset
    preset = _preset(preset_id)
    if preset.discovery_path is None:
        return list(preset.catalog)
    wire = target.protocol.wire_api
    request_headers = (native_headers(target) if wire in ('anthropic', 'gemini') else
                       {'Authorization': 'Bearer ' + target.api_key, 'User-Agent': 'RelayAuditor/experimental'})
    request_headers['Accept'] = 'application/json'
    url = preset.base_url + preset.discovery_path
    params = {}
    if preset_id.startswith('qwen-'):
        url = 'https://' + urlsplit(preset.base_url).netloc + preset.discovery_path
        params = {'model': target.model, 'capabilities': 'TG'}
    result = {}
    seen = set()
    try:
        for _ in range(MAX_MODEL_PAGES):
            request = Request(url + ('?' + urlencode(params) if params else ''), headers=request_headers, method='GET')
            raw, _ = read(request, opener, 15)
            rows, cursor = _model_page(preset_id, json.loads(raw))
            if not isinstance(rows, list):
                raise ValueError('invalid_models')
            result.update(dict.fromkeys(model_choices(rows)))
            if cursor is None or target.model in result:
                return list(result)
            if not isinstance(cursor, str) or not cursor or len(cursor) > 512 or cursor in seen:
                raise ValueError('invalid_models_cursor')
            seen.add(cursor)
            params = {'after_id' if preset_id == 'anthropic' else 'pageToken': cursor}
    except (AttributeError, KeyError, TypeError, ValueError):
        raise EndpointError('invalid_response') from None
    raise EndpointError('models_unavailable')
