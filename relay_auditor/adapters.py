"""Native text-only wire adapters. No tools execute; reasoning text is discarded."""
import json
import math
import time
from http.client import IncompleteRead
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request

from .models import model_choices
from .transport import Completion,EndpointError,MAX_RESPONSE,_usage


def headers(target):
    value={'Content-Type':'application/json','Accept':'application/json, text/event-stream','User-Agent':'RelayAuditor/experimental'}
    if target.protocol.wire_api=='anthropic':
        value.update({'x-api-key':target.api_key,'anthropic-version':'2023-06-01'})
    else: value['x-goog-api-key']=target.api_key
    return value


def read(request,opener,timeout,*,official_generation=False):
    try:
        with opener(request,timeout=timeout) as response:
            raw=response.read(MAX_RESPONSE+1)
            mime=response.headers.get('Content-Type','')
        if len(raw)>MAX_RESPONSE: raise EndpointError('response_too_large')
        return raw.decode('utf-8'),mime
    except HTTPError as error:
        status=error.code; error.close()
        if official_generation and status == 404:
            raise EndpointError('reference_model_unavailable') from None
        raise EndpointError('authentication_failed' if status in (401,403) else 'rate_limited' if status==429 else
                            'unsupported_parameters' if status in (400,422) else 'http_error') from None
    except EndpointError: raise
    except (IncompleteRead,TimeoutError,OSError,URLError): raise EndpointError('network_error') from None
    except UnicodeError: raise EndpointError('invalid_response') from None


def list_models(target,opener):
    raw,_=read(Request(target.base_url.rstrip('/')+'/models',headers=headers(target),method='GET'),opener,15)
    try:
        body=json.loads(raw)
        if target.protocol.wire_api=='anthropic':
            if not isinstance(body.get('data'),list): raise ValueError()
            return model_choices(body['data'])
        rows=body.get('models')
        if not isinstance(rows,list): raise ValueError()
        return model_choices([{'id':r.get('name','').removeprefix('models/')} for r in rows if isinstance(r,dict)
                              and 'generateContent' in r.get('supportedGenerationMethods',['generateContent'])])
    except (ValueError,TypeError,AttributeError): raise EndpointError('invalid_response') from None


def complete(target,case,opener):
    protocol=target.protocol; effort=protocol.reasoning_effort; anthropic=protocol.wire_api=='anthropic'
    if anthropic:
        body={'model':target.model,'max_tokens':protocol.max_output_tokens,'stream':protocol.stream,'messages':[case.payload()]}
        if effort=='none': body['thinking']={'type':'disabled'}
        elif effort:
            if effort not in ('low','medium','high','max'): raise EndpointError('unsupported_parameters')
            body.update(thinking={'type':'adaptive'},output_config={'effort':effort})
        route='/messages'
        if protocol.temperature is not None: body['temperature']=protocol.temperature
    else:
        config={'maxOutputTokens':protocol.max_output_tokens}
        if effort=='none': config['thinkingConfig']={'thinkingBudget':0}
        elif effort:
            if effort not in ('minimal','low','medium','high'): raise EndpointError('unsupported_parameters')
            config['thinkingConfig']={'thinkingLevel':effort.upper()}
        if protocol.temperature is not None: config['temperature']=protocol.temperature
        body={'contents':[{'role':'user','parts':[{'text':case.prompt}]}],'generationConfig':config}
        route='/models/'+quote(target.model.removeprefix('models/'),safe='')+(':'+('streamGenerateContent?alt=sse' if protocol.stream else 'generateContent'))
    started=time.monotonic()
    request = Request(target.base_url.rstrip('/')+route,data=json.dumps(body).encode(),headers=headers(target),method='POST')
    text,mime=read(request,opener,90,official_generation=bool(target.official_preset))
    try:
        stream='text/event-stream' in mime or text.lstrip().startswith(('data:','event:'))
        events=[json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:') and line[5:].strip() not in ('','[DONE]')] if stream else [json.loads(text)]
        chunks=[]; raw_usage={}; terminal=False; intact=True; issue=None
        for event in events:
            if not isinstance(event,dict) or 'error' in event: raise EndpointError('remote_error')
            if anthropic:
                kind=event.get('type')
                message=event.get('message',{}) if kind=='message_start' else event
                raw_usage.update(message.get('usage',{}))
                for part in message.get('content',[]):
                    if part.get('type')=='text': chunks.append(part.get('text',''))
                if kind=='content_block_delta' and event.get('delta',{}).get('type')=='text_delta': chunks.append(event['delta'].get('text',''))
                stop=event.get('delta',{}).get('stop_reason') or event.get('stop_reason')
                if stop and stop not in ('end_turn','stop_sequence'):
                    intact=False
                    issue = 'output_limit' if stop == 'max_tokens' else 'incomplete_output'
                terminal=terminal or kind=='message_stop' or (not stream and bool(stop))
            else:
                if event.get('promptFeedback',{}).get('blockReason'): raise EndpointError('remote_error')
                raw_usage.update(event.get('usageMetadata',{}))
                rows=event.get('candidates',[])
                for row in rows[:1]:
                    for part in row.get('content',{}).get('parts',[]):
                        if not part.get('thought') and isinstance(part.get('text'),str): chunks.append(part['text'])
                    finish=row.get('finishReason')
                    terminal=terminal or bool(finish)
                    if finish and finish!='STOP':
                        intact=False
                        issue = 'output_limit' if finish == 'MAX_TOKENS' else 'incomplete_output'
        usage=None
        if anthropic and all(type(raw_usage.get(k)) is int for k in ('input_tokens','output_tokens')):
            cached=raw_usage.get('cache_read_input_tokens',0); created=raw_usage.get('cache_creation_input_tokens',0)
            if type(cached) is int and type(created) is int and min(cached,created)>=0:
                usage=_usage({'input_tokens':raw_usage['input_tokens']+cached+created,'output_tokens':raw_usage['output_tokens'],
                              'input_tokens_details':{'cached_tokens':cached}})
        elif not anthropic and all(type(raw_usage.get(k)) is int for k in ('promptTokenCount','candidatesTokenCount')):
            reasoning=raw_usage.get('thoughtsTokenCount',0)
            if type(reasoning) is int and reasoning>=0:
                usage=_usage({'input_tokens':raw_usage['promptTokenCount'],'output_tokens':raw_usage['candidatesTokenCount']+reasoning,
                              'input_tokens_details':{'cached_tokens':raw_usage.get('cachedContentTokenCount',0)},
                              'output_tokens_details':{'reasoning_tokens':reasoning}})
        answer = ''.join(chunks)
        if not terminal:
            issue = issue or ('stream_interrupted' if stream else 'incomplete_output')
        elif not answer.strip():
            issue = issue or 'empty_answer'
        return Completion(answer,usage,time.monotonic()-started,intact and terminal,issue)
    except EndpointError: raise
    except (ValueError,TypeError,AttributeError,KeyError): raise EndpointError('invalid_response') from None
