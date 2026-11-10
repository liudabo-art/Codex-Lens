"""Opt-in, memory-only API credentials; fixed official reference origin."""
from __future__ import annotations

from dataclasses import dataclass, field
from http.client import IncompleteRead
from io import BytesIO
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .protocol import Protocol, ProbeCase, model_name, OFFICIAL_ENDPOINTS, DEEPSEEK_DIRECT

MAX_RESPONSE = 2 * 1024 * 1024


class EndpointError(Exception):
    pass


@dataclass(frozen=True, repr=False)
class Target:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str
    protocol: Protocol
    role: str = 'relay'
    official_preset: str | None = None

    def __post_init__(self):
        try:
            parts = urlsplit(self.base_url)
            port = parts.port
            valid = (parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password
                     and not parts.query and not parts.fragment and not re.search(r'[\s\\]', self.base_url))
        except (ValueError, TypeError):
            valid = False
        if not valid or len(self.base_url) > 2048:
            raise ValueError('invalid_endpoint')
        if not isinstance(self.api_key, str) or not self.api_key or len(self.api_key) > 16000 or re.search(r'[\r\n]', self.api_key):
            raise ValueError('invalid_credential')
        direct = self.base_url.rstrip('/') in DEEPSEEK_DIRECT
        if self.role == 'relay' and direct:
            object.__setattr__(self, 'role', 'official_api')
        if self.role not in ('relay', 'reference', 'official_api') or self.role == 'official_api' and not direct:
            raise ValueError('invalid_role')
        if self.official_preset is not None:
            from .official import PRESETS, official_model

            candidate = official_model(self.official_preset, self.model)
            preset = PRESETS[self.official_preset]
            if (self.role != 'reference' or self.base_url != preset.base_url
                    or self.protocol.wire_api not in preset.wires):
                raise ValueError('reference_origin_must_be_official')
            if candidate != self.model:
                raise ValueError('reference_model_mismatch')
        elif self.role == 'reference' and self.base_url.rstrip('/') != OFFICIAL_ENDPOINTS[self.protocol.wire_api]:
            raise ValueError('reference_origin_must_be_official')
        if self.role == 'relay' and parts.hostname.lower().rstrip('.') in ('api.openai.com', 'chatgpt.com', 'chat.openai.com','api.anthropic.com','generativelanguage.googleapis.com','api.deepseek.com'):
            raise ValueError('official_api_is_reference_only')
        model_name(self.model)

    def __repr__(self):
        return '<Target: private runtime configuration>'


@dataclass(repr=False)
class Completion:
    text: str = field(repr=False)
    usage: dict | None = None
    elapsed_seconds: float = 0
    complete: bool = True
    issue: str | None = None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EndpointError('redirect_blocked')


def _usage(value):
    if not isinstance(value, dict):
        return None
    source = [('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')]
    result = {}
    for a, b in source:
        item = value.get(a, value.get(b))
        if type(item) not in (int, float) or not math.isfinite(item) or item < 0:
            return None
        result[a] = int(item)
    result['total_tokens'] = result['input_tokens'] + result['output_tokens']
    for source_key, inner, target in (
        ('input_tokens_details', 'cached_tokens', 'cached_input_tokens'),
        ('prompt_tokens_details', 'cached_tokens', 'cached_input_tokens'),
        ('output_tokens_details', 'reasoning_tokens', 'reasoning_output_tokens'),
        ('completion_tokens_details', 'reasoning_tokens', 'reasoning_output_tokens')):
        details = value.get(source_key)
        n = details.get(inner) if isinstance(details, dict) else None
        if type(n) is int and 0 <= n <= result['input_tokens' if 'input' in target else 'output_tokens']:
            result[target] = n
    return result


def _extract(body, chunks, state):
    if not isinstance(body, dict):
        return
    if isinstance(body.get('error'), dict):
        raise EndpointError('remote_error')
    if isinstance(body.get('usage'), dict):
        state['usage'] = _usage(body['usage'])
    if body.get('status') in ('incomplete', 'failed', 'cancelled'):
        state['complete'] = False
        details = body.get('incomplete_details') or {}
        state['issue'] = 'output_limit' if isinstance(details, dict) and details.get('reason') == 'max_output_tokens' else 'incomplete_output'
    if isinstance(body.get('output_text'), str):
        chunks.append(body['output_text'])
    for item in body.get('output', []) if isinstance(body.get('output'), list) else []:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        for part in item.get('content', []) if isinstance(item.get('content'), list) else []:
            if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                chunks.append(part['text'])
    for choice in body.get('choices', []) if isinstance(body.get('choices'), list) else []:
        if not isinstance(choice, dict):
            continue
        content = choice.get('delta', choice.get('message', {}))
        if isinstance(content, dict):
            value = content.get('content')
            if isinstance(value, str):
                chunks.append(value)
            elif isinstance(value, list):
                chunks.extend(part['text'] for part in value if isinstance(part, dict)
                              and part.get('type') == 'text' and isinstance(part.get('text'), str))
        if choice.get('finish_reason') in ('length', 'content_filter'):
            state['complete'] = False
            state['issue'] = 'output_limit' if choice['finish_reason'] == 'length' else 'response_filtered'


def _read_stream(response, chunks, state):
    remaining = MAX_RESPONSE
    saw_delta = False
    try:
        while line := response.readline(remaining + 1):
            remaining -= len(line)
            if remaining < 0:
                raise EndpointError('response_too_large')
            if not line.startswith(b'data:'):
                continue
            data = line[5:].strip()
            if data == b'[DONE]':
                return
            if not data:
                continue
            try:
                event = json.loads(data)
            except (ValueError, UnicodeError):
                if not line.endswith(b'\n'):
                    break  # The connection ended inside an event.
                raise
            if event.get('type') == 'response.output_text.delta':
                chunks.append(event.get('delta', ''))
                saw_delta = True
            elif event.get('type') in ('response.completed', 'response.incomplete'):
                summary = event.get('response', {})
                if saw_delta and isinstance(summary, dict):
                    summary = {k: v for k, v in summary.items() if k not in ('output', 'output_text')}
                _extract(summary, chunks, state)
                if event['type'] == 'response.incomplete':
                    state.update(complete=False, issue=state['issue'] or 'incomplete_output')
                return
            elif event.get('type') in ('response.failed', 'error'):
                raise EndpointError('remote_error')
            else:
                _extract(event, chunks, state)
    except (IncompleteRead, OSError):
        pass  # A disconnect before a terminal event leaves the answer incomplete.
    state.update(complete=False, issue=state['issue'] or 'stream_interrupted')


class APIClient:
    def __init__(self, target: Target, open_request=None):
        self.target = target
        self._open = open_request or build_opener(ProxyHandler({}), NoRedirect()).open

    def list_models(self):
        if self.target.official_preset:
            from .official import list_models
            return list_models(self.target, self._open)
        if self.target.protocol.wire_api in ('anthropic','gemini'):
            from .adapters import list_models
            return list_models(self.target,self._open)
        from .models import model_choices
        request = Request(self.target.base_url.rstrip('/')+'/models', method='GET',
                          headers={'Authorization':'Bearer '+self.target.api_key, 'Accept':'application/json',
                                   'User-Agent':'RelayAuditor/experimental'})
        try:
            with self._open(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE+1)
            if len(raw) > MAX_RESPONSE:
                raise EndpointError('response_too_large')
            body = json.loads(raw)
            if not isinstance(body, dict) or not isinstance(body.get('data'), list):
                raise EndpointError('invalid_response')
            return model_choices(body['data'])
        except HTTPError as error:
            code = error.code; error.close()
            raise EndpointError('authentication_failed' if code in (401,403) else 'models_unavailable') from None
        except EndpointError:
            raise
        except (URLError, TimeoutError, OSError):
            raise EndpointError('network_error') from None
        except (ValueError, TypeError, UnicodeError):
            raise EndpointError('invalid_response') from None

    def complete(self, case: ProbeCase):
        if type(case) is not ProbeCase or len(case.prompt) > 262144:
            raise EndpointError('invalid_synthetic_case')
        target, protocol = self.target, self.target.protocol
        if target.official_preset:
            from .official import compatible_protocols
            if not compatible_protocols(target.official_preset, protocol, protocol, target.model):
                raise EndpointError('unsupported_parameters')
        if protocol.wire_api in ('anthropic','gemini'):
            from .adapters import complete
            return complete(target,case,self._open)
        body = {'model': target.model, 'stream': protocol.stream}
        if protocol.wire_api == 'responses':
            body.update(input=[case.payload()], max_output_tokens=protocol.max_output_tokens, store=False)
            if protocol.reasoning_effort:
                body['reasoning'] = {'effort': protocol.reasoning_effort}
            route = '/responses'
        elif protocol.wire_api == 'deepseek' or target.role == 'official_api' and protocol.wire_api == 'chat':
            body.update(messages=[case.payload()], max_tokens=protocol.max_output_tokens)
            effort = protocol.reasoning_effort
            if effort not in (None, 'none', 'low', 'high', 'max'):
                raise EndpointError('unsupported_parameters')
            if effort:
                body['thinking'] = {'type': 'disabled' if effort == 'none' else 'enabled'}
                if effort != 'none':
                    body['reasoning_effort'] = effort
            if protocol.stream:
                body['stream_options'] = {'include_usage': True}
            route = '/chat/completions'
        else:
            body['messages'] = [case.payload()]
            if target.official_preset:
                from .official import chat_options
                body.update(chat_options(target))
            else:
                body['max_completion_tokens'] = protocol.max_output_tokens
                if protocol.stream:
                    body['stream_options'] = {'include_usage': True}
                if protocol.reasoning_effort:
                    body['reasoning_effort'] = protocol.reasoning_effort
            route = '/chat/completions'
        if protocol.temperature is not None:
            body['temperature'] = protocol.temperature
        request = Request(target.base_url.rstrip('/') + route,
                          data=json.dumps(body, separators=(',', ':')).encode(), method='POST',
                          headers={'Authorization': 'Bearer ' + target.api_key, 'Content-Type': 'application/json',
                                   'Accept': 'application/json, text/event-stream', 'User-Agent': 'RelayAuditor/experimental'})
        started = time.monotonic()
        try:
            chunks, state = [], {'usage': None, 'complete': True, 'issue': None}
            with self._open(request, timeout=90) as response:
                content_type = response.headers.get('Content-Type', '')
                if 'text/event-stream' in content_type.lower():
                    _read_stream(response, chunks, state)
                else:
                    raw = response.read(MAX_RESPONSE + 1)
                    if len(raw) > MAX_RESPONSE:
                        raise EndpointError('response_too_large')
                    if raw.lstrip().startswith((b'data:', b'event:')):
                        _read_stream(BytesIO(raw), chunks, state)
                    else:
                        _extract(json.loads(raw), chunks, state)
            answer = ''.join(chunks)
            issue = state['issue'] or ('empty_answer' if not answer.strip() else None)
            return Completion(answer, state['usage'], time.monotonic() - started, state['complete'], issue)
        except HTTPError as error:
            code = error.code
            error.close()
            if code == 404 and target.official_preset:
                raise EndpointError('reference_model_unavailable') from None
            raise EndpointError('authentication_failed' if code in (401, 403) else
                                'rate_limited' if code == 429 else 'unsupported_parameters' if code in (400, 422)
                                else 'http_error') from None
        except EndpointError:
            raise
        except (IncompleteRead, URLError, TimeoutError, OSError):
            raise EndpointError('network_error') from None
        except (ValueError, UnicodeError, TypeError, AttributeError):
            raise EndpointError('invalid_response') from None
