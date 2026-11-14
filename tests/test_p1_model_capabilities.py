"""DeepSeek/Gemini model parameters on existing native text wires only."""
import io
import json
import unittest

from relay_auditor.model_capabilities import allowed_reasoning_efforts, reasoning_catalog, supports_parameters
from relay_auditor.official import compatible_protocols
from relay_auditor.protocol import Protocol, make_case
from relay_auditor.transport import APIClient, EndpointError, Target


class Response(io.BytesIO):
    headers = {'Content-Type': 'application/json'}

    def __init__(self):
        super().__init__(b'{"choices":[{"message":{"content":"7"},"finish_reason":"stop"}],'
                         b'"candidates":[{"content":{"parts":[{"text":"7"}]},"finishReason":"STOP"}]}')


class P1ModelParametersTests(unittest.TestCase):
    def test_catalog_offers_only_exact_canonical_native_choices(self):
        cases = [
            ('deepseek-flash', 'deepseek', ('none', 'low', 'high', 'max')),
            ('deepseek-v4-pro', 'chat', ('none', 'low', 'high', 'max')),
            ('deepseek-primary', 'deepseek', ()),
            ('deepseek-v4-flash', 'deepseek', ()),
            ('gemini-2.5-pro', 'gemini', ()),
            ('gemini-2.5-flash', 'gemini', ('none',)),
            ('gemini-2.5-flash-lite', 'gemini', ('none',)),
            ('gemini-3-pro-preview', 'gemini', ('low', 'high')),
            ('gemini-3.1-pro-preview', 'gemini', ('low', 'medium', 'high')),
            ('gemini-3-flash-preview', 'gemini', ('minimal', 'low', 'medium', 'high')),
            ('gemini-3.8-flash', 'gemini', ('low', 'medium', 'high')),
            ('gemini-4-hydrogen', 'gemini', ('low', 'medium', 'high', 'xhigh')),
            ('gemini-3.1-pro-preview', 'chat', ()),
            ('gemini-unknown', 'gemini', ()),
        ]
        catalog = reasoning_catalog()
        for model, wire, expected in cases:
            with self.subTest(model=model, wire=wire):
                self.assertEqual(allowed_reasoning_efforts(model, wire), expected)
                self.assertEqual(catalog.get(model, {}).get(wire, []), list(expected))
        self.assertEqual(catalog['models/gemini-3-flash-preview'], catalog['gemini-3-flash-preview'])

    def test_invalid_native_parameters_fail_before_http(self):
        cases = [
            ('deepseek-unknown', 'deepseek', 'high', None),
            ('deepseek-v4-flash', 'deepseek', 'none', None),
            ('deepseek-flash', 'deepseek', None, 0),
            ('deepseek-flash', 'deepseek', 'high', 0),
            ('deepseek-v4-pro', 'chat', 'max', 1),
            ('gemini-2.5-pro', 'gemini', 'high', None),
            ('gemini-2.5-pro', 'gemini', 'none', None),
            ('gemini-2.5-flash', 'gemini', 'low', None),
            ('gemini-2.5-flash-lite', 'gemini', 'high', None),
            ('gemini-3-pro-preview', 'gemini', 'medium', None),
            ('gemini-3.1-pro-preview', 'gemini', 'minimal', None),
            ('gemini-3-flash-preview', 'gemini', 'none', None),
            ('gemini-3.8-flash', 'gemini', 'minimal', None),
            ('gemini-3.6-flash', 'gemini', 'high', 1),
            ('gemini-4-hydrogen', 'gemini', 'max', None),
            ('gemini-4-hydrogen', 'gemini', None, 1),
            ('gemini-unknown', 'gemini', 'high', None),
        ]
        for model, wire, effort, temperature in cases:
            with self.subTest(model=model, wire=wire, effort=effort, temperature=temperature):
                sent = []
                def send(request, timeout):
                    sent.append(request)
                    return Response()
                protocol = Protocol(wire, reasoning_effort=effort, temperature=temperature)
                self.assertFalse(supports_parameters(model, protocol))
                target = Target('https://relay.example/v1', 'synthetic-key', model, protocol)
                with self.assertRaisesRegex(EndpointError, '^unsupported_parameters$'):
                    APIClient(target, send).complete(make_case('digit', 1))
                self.assertEqual(sent, [])

    def test_deepseek_verified_effort_aliases_are_sent_without_local_remapping(self):
        for model in ('deepseek-flash', 'deepseek-v4-pro'):
            for effort in ('none', 'low', 'high', 'max', 'minimal', 'medium', 'xhigh'):
                with self.subTest(model=model, effort=effort):
                    sent = []
                    def send(request, timeout):
                        sent.append(json.loads(request.data))
                        return Response()
                    protocol = Protocol('deepseek', reasoning_effort=effort, max_output_tokens=8192, stream=True)
                    target = Target('https://relay.example/v1', 'synthetic-key', model, protocol)
                    self.assertEqual(APIClient(target, send).complete(make_case('digit', 1)).text, '7')
                    self.assertEqual(sent[0]['model'], model)
                    self.assertEqual(sent[0]['max_tokens'], 8192)
                    self.assertIs(sent[0]['stream'], True)
                    self.assertEqual(sent[0]['thinking'], {'type': 'disabled' if effort == 'none' else 'enabled'})
                    if effort != 'none':
                        self.assertEqual(sent[0]['reasoning_effort'], effort)
                    else:
                        self.assertNotIn('reasoning_effort', sent[0])

    def test_gemini_legacy_budget_and_named_level_requests_stay_distinct(self):
        cases = [
            ('gemini-2.5-flash', 'none', {'thinkingBudget': 0}),
            ('gemini-2.5-flash-lite', 'none', {'thinkingBudget': 0}),
            ('gemini-3-pro-preview', 'low', {'thinkingLevel': 'LOW'}),
            ('gemini-3.1-pro-preview', 'medium', {'thinkingLevel': 'MEDIUM'}),
            ('gemini-3-flash-preview', 'minimal', {'thinkingLevel': 'MINIMAL'}),
            ('models/gemini-3-flash-preview', 'high', {'thinkingLevel': 'HIGH'}),
            ('gemini-3.8-flash', 'high', {'thinkingLevel': 'HIGH'}),
            ('gemini-4-hydrogen', 'xhigh', {'thinkingLevel': 'XHIGH'}),
        ]
        for model, effort, expected in cases:
            with self.subTest(model=model, effort=effort):
                sent = []
                def send(request, timeout):
                    sent.append((request.full_url, json.loads(request.data)))
                    return Response()
                protocol = Protocol('gemini', reasoning_effort=effort, max_output_tokens=8192, stream=True)
                target = Target('https://relay.example/v1beta', 'synthetic-key', model, protocol)
                self.assertEqual(APIClient(target, send).complete(make_case('digit', 1)).text, '7')
                self.assertEqual(sent[0][0], 'https://relay.example/v1beta/models/'
                                 + model.removeprefix('models/') + ':streamGenerateContent?alt=sse')
                config = sent[0][1]['generationConfig']
                self.assertEqual(config, {'maxOutputTokens': 8192, 'thinkingConfig': expected})

    def test_official_matching_and_effective_temperature_obey_the_shared_policy(self):
        cases = [
            ('deepseek', 'deepseek-flash', 'deepseek', 'medium', None, True),
            ('deepseek', 'deepseek-v4-pro', 'deepseek', 'none', 0.25, True),
            ('deepseek', 'deepseek-flash', 'deepseek', None, 0.25, False),
            ('google', 'gemini-2.5-pro', 'gemini', None, 0.25, True),
            ('google', 'gemini-2.5-pro', 'gemini', 'none', None, False),
            ('google', 'gemini-3.1-pro-preview', 'gemini', 'high', 0.5, True),
            ('google', 'gemini-3-flash-preview', 'gemini', 'high', 0.5, True),
            ('google', 'gemini-3-pro-preview', 'gemini', 'medium', None, False),
            ('google', 'gemini-3.8-flash', 'gemini', 'low', 1, False),
        ]
        for preset, model, wire, effort, temperature, expected in cases:
            with self.subTest(model=model, effort=effort, temperature=temperature):
                protocol = Protocol(wire, reasoning_effort=effort, temperature=temperature)
                self.assertEqual(supports_parameters(model, protocol), expected)
                self.assertEqual(compatible_protocols(preset, protocol, protocol, model), expected)

    def test_supported_temperatures_and_unknown_defaults_remain_unchanged(self):
        cases = [
            ('deepseek-flash', 'deepseek', 'none', 0.25),
            ('deepseek-v4-pro', 'chat', 'none', 0.25),
            ('gemini-2.5-pro', 'gemini', None, 0.25),
            ('gemini-3.1-pro-preview', 'gemini', 'high', 0.5),
            ('gemini-3-flash-preview', 'gemini', 'high', 0.5),
            ('deepseek-unknown', 'deepseek', None, None),
            ('gemini-unknown', 'gemini', None, None),
        ]
        for model, wire, effort, temperature in cases:
            with self.subTest(model=model, wire=wire):
                sent = []
                def send(request, timeout):
                    sent.append(json.loads(request.data))
                    return Response()
                protocol = Protocol(wire, reasoning_effort=effort, temperature=temperature)
                target = Target('https://relay.example/v1', 'synthetic-key', model, protocol)
                self.assertEqual(APIClient(target, send).complete(make_case('digit', 1)).text, '7')
                body = sent[0]['generationConfig'] if wire == 'gemini' else sent[0]
                if temperature is None:
                    self.assertNotIn('temperature', body)
                else:
                    self.assertEqual(body['temperature'], temperature)
                if effort is None:
                    for key in ('thinking', 'reasoning', 'reasoning_effort', 'thinkingConfig'):
                        self.assertNotIn(key, body)
                self.assertEqual(protocol.reasoning_effort, effort)
                self.assertEqual(protocol.temperature, temperature)


if __name__ == '__main__':
    unittest.main()
