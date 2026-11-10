import io
import json
import unittest
from http.client import IncompleteRead
from urllib.error import HTTPError

from relay_auditor.protocol import Protocol, make_case
from relay_auditor.transport import Target, APIClient, EndpointError


class Response(io.BytesIO):
    def __init__(self, data, content_type='application/json'):
        super().__init__(data)
        self.headers = {'Content-Type': content_type}


class TransportTests(unittest.TestCase):
    def test_only_synthetic_case_is_sent_and_answers_are_not_sent(self):
        captured = []
        def open_request(request, timeout):
            captured.append(request)
            return Response(b'{"output":[{"type":"message","content":[{"type":"output_text","text":"{\\"answer\\":3}"}]}],"usage":{"input_tokens":20,"output_tokens":5}}')
        client = APIClient(Target('https://relay.example/v1', 'PRIVATE-KEY', 'model-a', Protocol()), open_request)
        result = client.complete(make_case('trace', 1))
        body = json.loads(captured[0].data)
        self.assertEqual(captured[0].full_url, 'https://relay.example/v1/responses')
        self.assertEqual(body['model'], 'model-a')
        self.assertEqual(body['store'], False)
        self.assertNotIn('expected', body)
        self.assertEqual(result.usage['total_tokens'], 25)
        self.assertEqual(result.text, '{"answer":3}')

    def test_chat_stream_is_parsed_without_exposing_reasoning(self):
        data = b'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE-RAW","content":"7"}}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":3}}\n\ndata: [DONE]\n\n'
        target = Target('https://relay.example/v1', 'PRIVATE-KEY', 'model-a', Protocol(wire_api='chat'))
        result = APIClient(target, lambda *args, **kw: Response(data, 'text/event-stream')).complete(make_case('digit', 0))
        self.assertEqual(result.text, '7')
        self.assertEqual(result.usage['total_tokens'], 12)

    def test_missing_usage_is_unknown_and_not_zero(self):
        result = APIClient(Target('https://relay.example/v1', 'k', 'model-a', Protocol()),
                           lambda *args, **kw: Response(b'{"output_text":"7"}')).complete(make_case('digit', 0))
        self.assertIsNone(result.usage)

    def test_error_body_url_and_key_are_not_exposed(self):
        def fail(request, timeout):
            raise HTTPError(request.full_url, 401, 'PRIVATE-RAW', {}, io.BytesIO(b'PRIVATE-KEY'))
        target = Target('https://relay.example/v1', 'PRIVATE-KEY', 'model-a', Protocol())
        with self.assertRaises(EndpointError) as error:
            APIClient(target, fail).complete(make_case('digit', 0))
        self.assertEqual(str(error.exception), 'authentication_failed')
        self.assertNotIn('PRIVATE', repr(target))
        self.assertNotIn('relay.example', repr(target))

    def test_private_http_and_credential_urls_are_rejected(self):
        for value in ('http://relay.example/v1', 'https://user:pass@relay.example/v1',
                      'https://relay.example/v1?key=secret', 'https://relay.example/v1#key'):
            with self.subTest():
                with self.assertRaises(ValueError):
                    Target(value, 'k', 'model-a', Protocol())

    def test_reference_credentials_only_go_to_fixed_official_api(self):
        with self.assertRaises(ValueError):
            Target('https://relay.example/v1', 'official-key', 'model-a', Protocol(), role='reference')
        with self.assertRaises(ValueError):
            Target('https://api.openai.com/v1', 'key', 'model-a', Protocol(), role='relay')

    def test_truncated_stream_cannot_be_graded_as_complete(self):
        raw = b'data: {"type":"response.output_text.delta","delta":"7"}\n\n'
        result = APIClient(Target('https://relay.example/v1', 'k', 'model-a', Protocol()),
                           lambda *a, **kw: Response(raw, 'text/event-stream')).complete(make_case('digit', 0))
        self.assertFalse(result.complete)

    def test_responses_completion_does_not_wait_for_connection_close(self):
        class DelayedClose(Response):
            def read(self, size=-1):
                raise TimeoutError()
            def readline(self, size=-1):
                line = super().readline(size)
                if not line:
                    raise TimeoutError()
                return line
        raw = b'data: {"type":"response.completed","response":{"status":"completed","output_text":"7"}}\n\n'
        result = APIClient(Target('https://relay.example/v1', 'k', 'model-a', Protocol()),
                           lambda *a, **kw: DelayedClose(raw, 'text/event-stream')).complete(make_case('digit', 0))
        self.assertTrue(result.complete)
        self.assertEqual(result.text, '7')

    def test_incomplete_http_body_is_classified_as_connection_failure(self):
        class IncompleteBody(Response):
            def read(self, size=-1):
                raise IncompleteRead(b'synthetic')
        with self.assertRaisesRegex(EndpointError, '^network_error$'):
            APIClient(Target('https://relay.example/v1', 'k', 'model-a', Protocol()),
                      lambda *a, **kw: IncompleteBody(b'')).complete(make_case('digit', 0))

    def test_explicit_output_limit_is_distinct_from_missing_terminal_event(self):
        raw = (b'data: {"type":"response.incomplete","response":{"status":"incomplete",'
               b'"incomplete_details":{"reason":"max_output_tokens"}}}\n\n')
        result = APIClient(Target('https://relay.example/v1', 'k', 'model-a', Protocol()),
                           lambda *a, **kw: Response(raw, 'text/event-stream')).complete(make_case('digit', 0))
        self.assertFalse(result.complete)
        self.assertEqual(result.issue, 'output_limit')

    def test_stream_setting_is_explicit_and_changes_baseline_protocol(self):
        captured = []
        def opened(request, timeout):
            captured.append(json.loads(request.data))
            return Response(b'data: {"type":"response.output_text.delta","delta":"7"}\n\ndata: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":1,"output_tokens":1}}}\n\n', 'text/event-stream')
        protocol = Protocol(stream=True)
        self.assertNotEqual(protocol.identity, Protocol().identity)
        result = APIClient(Target('https://relay.example/v1','k','model-a',protocol),opened).complete(make_case('digit',0))
        self.assertTrue(captured[0]['stream'])
        self.assertTrue(result.complete)

    def test_urls_and_absolute_paths_are_not_accepted_as_model_identifiers(self):
        for model in ('https://private.invalid/token', 'C:/private/model'):
            with self.assertRaises(ValueError):
                Target('https://relay.example/v1','k',model,Protocol())

    def test_official_login_endpoints_are_never_relay_targets(self):
        for endpoint in ('https://chatgpt.com/backend-api/codex','https://api.openai.com./v1'):
            with self.assertRaises(ValueError):
                Target(endpoint,'synthetic-key','model-a',Protocol())


if __name__ == '__main__':
    unittest.main()
