import io
import json
import unittest
from dataclasses import replace
from urllib.error import HTTPError

from relay_auditor.official import (
    PRESETS, compatible_protocols, official_model, reference_target, restore_reference,
)
from relay_auditor.protocol import ProbeCase, Protocol
from relay_auditor.transport import APIClient, EndpointError, Target


KEY = 'synthetic-official-key'
CASE = ProbeCase('official-transport-test', 1, 'Reply with a synthetic answer.')
CHAT = {'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}]}
ANTHROPIC = {'content': [{'type': 'text', 'text': 'answer'}], 'stop_reason': 'end_turn'}
GEMINI = {'candidates': [{'content': {'parts': [{'text': 'answer'}]}, 'finishReason': 'STOP'}]}


class Response(io.BytesIO):
    headers = {'Content-Type': 'application/json'}

    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())


class OfficialTests(unittest.TestCase):
    def relay(self, model, protocol=None):
        return Target('https://relay.example/v1', 'synthetic-relay-key', model, protocol or Protocol('chat'))

    def test_matching_uses_reviewed_aliases_without_fuzzy_substitutions(self):
        self.assertEqual(official_model('openai', 'gpt5.6sol'), 'gpt-5.6-sol')
        self.assertEqual(official_model('google', 'models/gemini-3-flash-preview'), 'gemini-3-flash-preview')
        self.assertEqual(official_model('openai', 'gpt-5.6-mini'), 'gpt-5.6-mini')
        with self.assertRaisesRegex(ValueError, 'reference_provider_mismatch'):
            official_model('deepseek', 'gpt5.6sol')
        with self.assertRaisesRegex(ValueError, 'reference_model_retired'):
            official_model('deepseek', 'deepseek-v4-flash')
        for preset, model in [('openai', 'vendor/gpt-5.6-sol'), ('openai', 'gpt56sol'),
                              ('minimax-cn', 'MiniMax-fictional')]:
            with self.subTest(preset=preset, model=model), self.assertRaisesRegex(ValueError, 'reference_model_mismatch'):
                official_model(preset, model)
        with self.assertRaisesRegex(ValueError, 'invalid_reference_preset'):
            official_model('unlisted', 'gpt-5.6-sol')

    def test_fixed_generation_routes_and_authentication(self):
        expected = {
            'openai': ('api.openai.com/v1', 'gpt-5.6-sol', 'chat', 'max_completion_tokens'),
            'anthropic': ('api.anthropic.com/v1', 'claude-sonnet-4-6', 'anthropic', 'max_tokens'),
            'google': ('generativelanguage.googleapis.com/v1beta', 'gemini-3-flash-preview', 'gemini', 'maxOutputTokens'),
            'deepseek': ('api.deepseek.com', 'deepseek-flash', 'deepseek', 'max_tokens'),
            'qwen-beijing': ('dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus', 'chat', 'max_tokens'),
            'qwen-singapore': ('dashscope-intl.aliyuncs.com/compatible-mode/v1', 'qwen-plus', 'chat', 'max_tokens'),
            'qwen-virginia': ('dashscope-us.aliyuncs.com/compatible-mode/v1', 'qwen-plus', 'chat', 'max_tokens'),
            'qwen-hongkong': ('cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus', 'chat', 'max_tokens'),
            'glm-cn': ('open.bigmodel.cn/api/paas/v4', 'glm-4.7', 'chat', 'max_tokens'),
            'glm-intl': ('api.z.ai/api/paas/v4', 'glm-4.7', 'chat', 'max_tokens'),
            'kimi-cn': ('api.moonshot.cn/v1', 'kimi-k2.6', 'chat', 'max_completion_tokens'),
            'kimi-intl': ('api.moonshot.ai/v1', 'kimi-k2.6', 'chat', 'max_completion_tokens'),
            'minimax-cn': ('api.minimax.cn/v1', 'MiniMax-M3', 'chat', 'max_completion_tokens'),
            'minimax-intl': ('api.minimax.io/v1', 'MiniMax-M3', 'chat', 'max_completion_tokens'),
            'xai': ('api.x.ai/v1', 'grok-4', 'chat', 'max_tokens'),
            'mistral': ('api.mistral.ai/v1', 'mistral-large-latest', 'chat', 'max_tokens'),
        }
        self.assertEqual(set(expected), set(PRESETS))
        for preset, (host, model, wire, limit) in expected.items():
            with self.subTest(preset=preset):
                target = reference_target(preset, self.relay(model), KEY, official_model(preset, model))
                self.assertEqual(target.protocol.wire_api, wire)
                self.assertEqual(restore_reference(preset, KEY, model, target.protocol), target)

                def send(request, timeout):
                    self.assertEqual(request.method, 'POST')
                    headers = {k.lower(): v for k, v in request.header_items()}
                    body = json.loads(request.data)
                    if wire == 'anthropic':
                        self.assertEqual(request.full_url, 'https://' + host + '/messages')
                        self.assertEqual(headers['x-api-key'], KEY)
                        self.assertEqual(headers['anthropic-version'], '2023-06-01')
                        payload = ANTHROPIC
                    elif wire == 'gemini':
                        self.assertEqual(request.full_url, 'https://' + host + '/models/' + model + ':generateContent')
                        self.assertEqual(headers['x-goog-api-key'], KEY)
                        self.assertEqual(body['generationConfig'][limit], 2048)
                        self.assertEqual(body['contents'][0]['parts'][0]['text'], CASE.prompt)
                        return Response(GEMINI)
                    else:
                        self.assertEqual(request.full_url, 'https://' + host + '/chat/completions')
                        self.assertEqual(headers['authorization'], 'Bearer ' + KEY)
                        payload = CHAT
                    self.assertEqual(body['model'], model)
                    self.assertEqual(body[limit], 2048)
                    self.assertEqual(body['messages'], [CASE.payload()])
                    if preset.startswith('minimax-'):
                        self.assertIs(body['reasoning_split'], True)
                    return Response(payload)

                self.assertEqual(APIClient(target, send).complete(CASE).text, 'answer')

    def test_openai_responses_keeps_native_settings_and_disables_storage(self):
        relay = self.relay('gpt5.6sol', Protocol('responses', reasoning_effort='high'))
        target = reference_target('openai', relay, KEY, 'gpt-5.6-sol')

        def send(request, timeout):
            self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
            body = json.loads(request.data)
            self.assertIs(body['store'], False)
            self.assertEqual(body['reasoning'], {'effort': 'high'})
            self.assertEqual(body['model'], 'gpt-5.6-sol')
            self.assertEqual(body['input'], [CASE.payload()])
            return Response({'output_text': 'answer'})

        self.assertEqual(APIClient(target, send).complete(CASE).text, 'answer')

    def test_origin_wire_and_model_constraints_apply_on_restore(self):
        target = reference_target('kimi-cn', self.relay('kimi-k2.6'), KEY, 'kimi-k2.6')
        for changes in ({'base_url': 'https://api.moonshot.ai/v1'}, {'role': 'relay'},
                        {'protocol': Protocol('responses')}, {'model': 'gpt-5.6-sol'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(target, **changes)

    def test_cross_protocol_compatibility_does_not_translate_explicit_effort(self):
        relay = Protocol('chat')
        native = Protocol('anthropic')
        self.assertTrue(compatible_protocols('anthropic', relay, native))
        self.assertFalse(compatible_protocols('anthropic', replace(relay, reasoning_effort='high'),
                                              replace(native, reasoning_effort='high')))
        self.assertFalse(compatible_protocols('anthropic', relay, replace(native, stream=True)))
        self.assertFalse(compatible_protocols('minimax-intl', replace(relay, temperature=0),
                                              replace(relay, temperature=0)))
        self.assertTrue(compatible_protocols('openai', Protocol('responses'), Protocol('responses')))

    def test_discovery_paginates_without_sending_probe_data(self):
        rows = {
            'anthropic': ('claude-sonnet-4-6', 'after_id=page-1',
                          {'data': [{'id': 'claude-haiku-4-5'}], 'has_more': True, 'last_id': 'page-1'},
                          {'data': [{'id': 'claude-sonnet-4-6'}], 'has_more': False}),
            'google': ('gemini-3-flash-preview', 'pageToken=page-1',
                       {'models': [{'name': 'models/gemini-old', 'supportedGenerationMethods': ['embedContent']}],
                        'nextPageToken': 'page-1'},
                       {'models': [{'name': 'models/gemini-3-flash-preview', 'supportedGenerationMethods': ['generateContent']}]}),
        }
        for preset, (model, query, first, second) in rows.items():
            with self.subTest(preset=preset):
                target = reference_target(preset, self.relay(model), KEY, model)
                seen = []

                def send(request, timeout):
                    self.assertEqual(request.method, 'GET')
                    self.assertIsNone(request.data)
                    seen.append(request.full_url)
                    return Response(first if len(seen) == 1 else second)

                result = APIClient(target, send).list_models()
                self.assertIn(model, result)
                self.assertNotIn('gemini-old', result)
                self.assertEqual(len(seen), 2)
                self.assertIn(query, seen[1])

    def test_qwen_uses_exact_model_metadata_without_workspace_or_prompt(self):
        target = reference_target('qwen-singapore', self.relay('qwen-plus'), KEY, 'qwen-plus')

        def send(request, timeout):
            self.assertEqual(request.method, 'GET')
            self.assertIsNone(request.data)
            self.assertTrue(request.full_url.startswith('https://dashscope-intl.aliyuncs.com/api/v1/models?'))
            self.assertIn('model=qwen-plus', request.full_url)
            return Response({'output': {'models': [{'model': 'qwen-plus'}]}})

        self.assertEqual(APIClient(target, send).list_models(), ['qwen-plus'])

    def test_provider_specific_model_lists_preserve_only_unambiguous_text_aliases(self):
        cases = (
            ('xai', 'https://api.x.ai/v1/language-models', 'grok-4-latest',
             {'models': [{'id': 'grok-4', 'aliases': ['grok-4-latest', 'grok-ambiguous'],
                          'input_modalities': ['text'], 'output_modalities': ['text']},
                         {'id': 'grok-2', 'aliases': ['grok-ambiguous']},
                         {'id': 'grok-audio', 'output_modalities': ['audio']}]}),
            ('mistral', 'https://api.mistral.ai/v1/models', 'mistral-large-latest',
             [{'id': 'mistral-large-2601', 'aliases': ['mistral-large-latest'], 'capabilities': {'completion_chat': True}},
              {'id': 'mistral-non-chat', 'capabilities': {'completion_chat': False}}]),
        )
        for preset, url, model, payload in cases:
            with self.subTest(preset=preset):
                target = reference_target(preset, self.relay(model), KEY, model)

                def send(request, timeout):
                    self.assertEqual(request.full_url, url)
                    self.assertEqual(request.method, 'GET')
                    return Response(payload)

                result = APIClient(target, send).list_models()
                self.assertIn(model, result)
                for excluded in ('grok-ambiguous', 'grok-audio', 'mistral-non-chat'):
                    self.assertNotIn(excluded, result)

    def test_static_discovery_and_authorization_failure(self):
        def forbidden(request, timeout):
            self.fail('static catalog must not use network')

        target = reference_target('minimax-cn', self.relay('MiniMax-M3'), KEY, 'MiniMax-M3')
        self.assertIn(target.model, APIClient(target, forbidden).list_models())

        def unauthorized(request, timeout):
            self.assertEqual(request.method, 'GET')
            raise HTTPError(request.full_url, 403, 'synthetic error', {}, io.BytesIO())

        target = reference_target('openai', self.relay('gpt5.6sol'), KEY, 'gpt-5.6-sol')
        with self.assertRaisesRegex(EndpointError, 'authentication_failed'):
            APIClient(target, unauthorized).list_models()

    def test_official_generation_reports_unavailable_model_for_native_and_chat(self):
        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, 'synthetic error', {}, io.BytesIO())

        for preset, model in [('google', 'gemini-3-flash-preview'), ('openai', 'gpt-5.6-sol')]:
            with self.subTest(preset=preset):
                target = reference_target(preset, self.relay(model), KEY, model)
                with self.assertRaisesRegex(EndpointError, 'reference_model_unavailable'):
                    APIClient(target, missing).complete(CASE)
