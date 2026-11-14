"""Exact-model parameter policy, exercised through synthetic HTTP only."""
import io
import json
import unittest

from relay_auditor.official import compatible_protocols, restore_reference
from relay_auditor.model_capabilities import allowed_reasoning_efforts, supports_parameters
from relay_auditor.protocol import Protocol, make_case
from relay_auditor.transport import APIClient, EndpointError, Target


class Response(io.BytesIO):
    headers = {'Content-Type': 'application/json'}

    def __init__(self):
        super().__init__(b'{"output_text":"7","content":[{"type":"text","text":"7"}],"stop_reason":"end_turn"}')


class ModelParameterTests(unittest.TestCase):
    def test_public_catalog_matches_alias_capabilities_and_cannot_mutate_policy(self):
        from relay_auditor import model_capabilities

        catalog = model_capabilities.reasoning_catalog()
        self.assertEqual(catalog['gpt5.6sol']['responses'],
                         ['none', 'low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(catalog['gpt5.6sol'], catalog['gpt-5.6-sol'])
        self.assertEqual(catalog['gpt-5.3-codex'],
                         {'responses': ['low', 'medium', 'high', 'xhigh']})
        self.assertEqual(catalog['claude-haiku-4-5'], {'anthropic': ['none']})
        self.assertNotIn('gpt-unknown', catalog)
        catalog['gpt-5.6-sol']['responses'].clear()
        catalog['gpt-5.6-sol']['chat'].append('minimal')
        catalog['gpt5.6sol'].clear()
        catalog.clear()
        fresh = model_capabilities.reasoning_catalog()
        self.assertEqual(fresh['gpt-5.6-sol']['responses'],
                         ['none', 'low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(fresh['gpt5.6sol'], fresh['gpt-5.6-sol'])
        self.assertNotIn('minimal', model_capabilities.allowed_reasoning_efforts('gpt-5.6-sol', 'chat'))

    def test_choices_are_model_and_wire_specific(self):
        cases = [
            ('gpt-5', 'responses', ('minimal', 'low', 'medium', 'high')),
            ('gpt-5.1', 'chat', ('none', 'low', 'medium', 'high')),
            ('gpt-5.2', 'responses', ('none', 'low', 'medium', 'high', 'xhigh')),
            ('gpt-5.6-sol', 'chat', ('none', 'low', 'medium', 'high', 'xhigh', 'max')),
            ('gpt-6.1-sol', 'responses', ('low', 'medium', 'high', 'xhigh', 'max')),
            ('gpt-5.3-codex', 'responses', ('low', 'medium', 'high', 'xhigh')),
            ('gpt-5.3-codex', 'chat', ()),
            ('claude-opus-4-5', 'anthropic', ('none', 'low', 'medium', 'high')),
            ('claude-opus-4-6', 'anthropic', ('none', 'low', 'medium', 'high', 'max')),
            ('claude-opus-4-8', 'anthropic', ('none', 'low', 'medium', 'high', 'xhigh', 'max')),
            ('claude-opus-5-5', 'anthropic', ('low', 'medium', 'high', 'xhigh', 'max')),
            ('claude-sonnet-4-6', 'chat', ()),
            ('claude-haiku-4-5', 'anthropic', ('none',)),
            ('gpt-unknown', 'responses', ()),
            ('vendor/gpt-5.6-sol', 'responses', ()),
            ('gpt-5.6-sol-fictional', 'responses', ()),
        ]
        for model, wire, expected in cases:
            with self.subTest(model=model, wire=wire):
                self.assertEqual(allowed_reasoning_efforts(model, wire), expected)

    def test_invalid_explicit_settings_never_reach_http(self):
        cases = [
            ('gpt-5', 'responses', 'none', None),
            ('gpt-5.1', 'chat', 'minimal', None),
            ('gpt-5.1', 'responses', 'xhigh', None),
            ('gpt-5.3-codex', 'chat', 'high', None),
            ('gpt-6-astra', 'responses', 'none', None),
            ('gpt-unknown', 'responses', 'high', None),
            ('claude-sonnet-4-5-20250929', 'anthropic', 'high', None),
            ('claude-haiku-4-5', 'anthropic', 'low', None),
            ('claude-opus-4-5', 'anthropic', 'max', None),
            ('claude-opus-5-5', 'anthropic', 'none', None),
            ('claude-sonnet-5-5', 'anthropic', 'none', None),
            ('claude-unknown', 'anthropic', 'high', None),
            ('gpt-5', 'responses', None, 0),
            ('gpt-5.6-sol', 'responses', None, 0),
            ('claude-opus-4-6', 'anthropic', 'high', 0),
            ('claude-opus-4-8', 'anthropic', None, 0),
        ]
        for model, wire, effort, temperature in cases:
            with self.subTest(model=model, wire=wire, effort=effort, temperature=temperature):
                sent = []
                def send(request, timeout):
                    sent.append(request)
                    return Response()
                target = Target('https://relay.example/v1', 'synthetic-key', model,
                                Protocol(wire, reasoning_effort=effort, temperature=temperature))
                with self.assertRaisesRegex(EndpointError, '^unsupported_parameters$'):
                    APIClient(target, send).complete(make_case('digit', 1))
                self.assertEqual(sent, [])

    def test_official_matching_uses_the_same_exact_parameter_gate(self):
        cases = [
            ('openai', 'gpt-5', 'responses', 'none', False),
            ('openai', 'gpt-5', 'responses', 'minimal', True),
            ('openai', 'gpt-5.1', 'responses', 'xhigh', False),
            ('openai', 'gpt-5.6-sol', 'chat', 'max', True),
            ('openai', 'gpt-5.3-codex', 'chat', 'high', False),
            ('anthropic', 'claude-sonnet-4-5', 'anthropic', 'high', False),
            ('anthropic', 'claude-opus-4-5', 'anthropic', 'high', True),
            ('anthropic', 'claude-opus-4-6', 'anthropic', 'xhigh', False),
            ('anthropic', 'claude-opus-4-8', 'anthropic', 'xhigh', True),
            ('anthropic', 'claude-opus-5-5', 'anthropic', 'none', False),
        ]
        for preset, model, wire, effort, expected in cases:
            with self.subTest(model=model, effort=effort, wire=wire):
                protocol = Protocol(wire, reasoning_effort=effort)
                self.assertEqual(supports_parameters(model, protocol), expected)
                self.assertEqual(compatible_protocols(preset, protocol, protocol, model), expected)
                if not expected:
                    target = restore_reference(preset, 'synthetic-official-key', model, protocol)
                    with self.assertRaisesRegex(EndpointError, '^unsupported_parameters$'):
                        APIClient(target, lambda *a, **k: self.fail('invalid settings reached HTTP')).complete(make_case('digit', 1))

    def test_known_valid_settings_preserve_wire_output_stream_and_model(self):
        cases = [
            ('gpt-5', 'responses', 'minimal', None),
            ('gpt-5.1-2025-11-13', 'chat', 'none', 0.25),
            ('gpt-5.6-sol', 'responses', 'max', None),
            ('gpt-5.3-codex', 'responses', 'xhigh', None),
            ('claude-sonnet-4-6', 'anthropic', 'max', None),
            ('claude-opus-4-8', 'anthropic', 'xhigh', 1),
            ('claude-haiku-5-5', 'anthropic', 'none', None),
        ]
        for model, wire, effort, temperature in cases:
            with self.subTest(model=model, wire=wire):
                sent = []
                def send(request, timeout):
                    sent.append((request.full_url, json.loads(request.data)))
                    return Response()
                protocol = Protocol(wire, max_output_tokens=8192, reasoning_effort=effort,
                                    temperature=temperature, stream=True)
                target = Target('https://relay.example/v1', 'synthetic-key', model, protocol)
                self.assertEqual(APIClient(target, send).complete(make_case('digit', 1)).text, '7')
                url, body = sent[0]
                self.assertEqual(body['model'], model)
                self.assertIs(body['stream'], True)
                self.assertEqual(body[{'responses': 'max_output_tokens', 'chat': 'max_completion_tokens',
                                       'anthropic': 'max_tokens'}[wire]], 8192)
                if wire == 'anthropic':
                    self.assertTrue(url.endswith('/messages'))
                    if effort == 'none':
                        self.assertEqual(body['thinking'], {'type': 'disabled'})
                        self.assertNotIn('output_config', body)
                    else:
                        self.assertEqual(body['thinking'], {'type': 'adaptive'})
                        self.assertEqual(body['output_config'], {'effort': effort})
                elif wire == 'responses':
                    self.assertTrue(url.endswith('/responses'))
                    self.assertEqual(body['reasoning'], {'effort': effort})
                    self.assertIs(body['store'], False)
                else:
                    self.assertTrue(url.endswith('/chat/completions'))
                    self.assertEqual(body['reasoning_effort'], effort)
                if temperature is not None:
                    self.assertEqual(body['temperature'], temperature)
                else:
                    self.assertNotIn('temperature', body)

    def test_unknown_model_default_and_other_provider_compatibility_remain_usable(self):
        cases = [('gpt-unknown', 'responses', None), ('claude-unknown', 'anthropic', None),
                 ('qwen-plus', 'chat', 'high')]
        for model, wire, effort in cases:
            with self.subTest(model=model, wire=wire):
                sent = []
                def send(request, timeout):
                    sent.append(json.loads(request.data))
                    return Response()
                target = Target('https://relay.example/v1', 'synthetic-key', model,
                                Protocol(wire, reasoning_effort=effort))
                self.assertEqual(APIClient(target, send).complete(make_case('digit', 1)).text, '7')
                self.assertEqual(sent[0]['model'], model)
                if effort is None:
                    for key in ('thinking', 'reasoning', 'reasoning_effort', 'output_config'):
                        self.assertNotIn(key, sent[0])
                else:
                    self.assertEqual(sent[0]['reasoning_effort'], 'high')

    def test_temperature_uses_effective_model_default_without_rewriting_settings(self):
        cases = [
            ('gpt-5', None, 0, False), ('gpt-5.1', None, 0, True),
            ('gpt-5.4', None, 0, True), ('gpt-5.6-sol', None, 0, False),
            ('gpt-5.6-sol', 'none', 0, True), ('gpt-4.1', None, 2, True),
            ('claude-opus-4-5', 'high', 0, True), ('claude-opus-4-6', 'high', 0, False),
            ('claude-opus-4-6', None, 0, True), ('claude-opus-4-8', None, 0, False),
            ('claude-opus-4-8', 'high', 1, True),
        ]
        for model, effort, temperature, expected in cases:
            with self.subTest(model=model, effort=effort, temperature=temperature):
                wire = 'anthropic' if model.startswith('claude-') else 'responses'
                protocol = Protocol(wire, reasoning_effort=effort, temperature=temperature)
                self.assertEqual(supports_parameters(model, protocol), expected)
                self.assertEqual(protocol.reasoning_effort, effort)
                self.assertEqual(protocol.temperature, temperature)

    def test_opus_45_effort_does_not_invent_adaptive_thinking_or_token_budget(self):
        for model in ('claude-opus-4-5', 'claude-opus-4-5-20251101'):
            with self.subTest(model=model):
                sent = []
                def send(request, timeout):
                    sent.append(json.loads(request.data))
                    return Response()
                target = Target('https://relay.example/v1', 'synthetic-key', model,
                                Protocol('anthropic', reasoning_effort='high'))
                APIClient(target, send).complete(make_case('digit', 1))
                self.assertEqual(sent[0]['output_config'], {'effort': 'high'})
                self.assertNotIn('thinking', sent[0])


if __name__ == '__main__':
    unittest.main()
