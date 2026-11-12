import json
import tempfile
import unittest

from relay_auditor.core import Auditor
from relay_auditor.exam import exam_cases
from relay_auditor.protocol import Protocol
from relay_auditor.transport import APIClient, Target
from relay_auditor.transport import EndpointError, MAX_RESPONSE
from test_transport import Response


class ExamTransportTests(unittest.TestCase):
    def test_exam_questions_pass_the_real_transport_boundary(self):
        case, _ = next(exam_cases('gpt', 120, 42))
        captured = []

        def open_request(request, timeout):
            captured.append(json.loads(request.data))
            return Response(json.dumps({'output_text': json.dumps({'answer': case.expected})}).encode())

        target = Target('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol())
        result = APIClient(target, open_request).complete(case)
        self.assertTrue(case.grade(result.text)['correct'])
        self.assertEqual(len(captured), 1)
        self.assertNotIn('expected', captured[0])
        self.assertNotIn('variant', captured[0])

    def test_complete_json_with_a_stream_content_type_is_not_a_disconnect(self):
        case, _ = next(exam_cases('gpt', 120, 42))
        for wire in ('responses', 'chat'):
            with self.subTest(wire=wire):
                answer = json.dumps({'answer': case.expected})
                body = ({'output_text': answer} if wire == 'responses' else
                        {'choices': [{'message': {'content': answer}, 'finish_reason': 'stop'}]})
                body['usage'] = {'input_tokens': 20, 'output_tokens': 10}
                reply = json.dumps(body, indent=2).encode()
                target = Target('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol(wire_api=wire))
                result = APIClient(target, lambda *args, **kwargs: Response(reply, 'text/event-stream')).complete(case)
                self.assertTrue(result.complete)
                self.assertIsNone(result.issue)
                self.assertTrue(case.grade(result.text)['correct'])
                self.assertEqual(result.usage['total_tokens'], 30)

    def test_mislabeled_json_keeps_output_limit_and_response_size_checks(self):
        case, _ = next(exam_cases('gpt', 120, 42))
        target = Target('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol())
        partial = json.dumps({'output_text': '{"answer":7}', 'status': 'incomplete',
                              'incomplete_details': {'reason': 'max_output_tokens'}}).encode()
        result = APIClient(target, lambda *args, **kwargs: Response(partial, 'text/event-stream')).complete(case)
        self.assertFalse(result.complete)
        self.assertEqual(result.issue, 'output_limit')
        oversized = b'{\n"output_text":"' + b'a' * MAX_RESPONSE + b'"}'
        with self.assertRaisesRegex(EndpointError, 'response_too_large'):
            APIClient(target, lambda *args, **kwargs: Response(oversized, 'text/event-stream')).complete(case)

    def test_json_after_an_sse_field_does_not_replace_a_missing_terminal_event(self):
        case, _ = next(exam_cases('gpt', 120, 42))
        body = b'event: response.completed\n' + json.dumps({'output_text': json.dumps({'answer': case.expected})}).encode()
        target = Target('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol())
        result = APIClient(target, lambda *args, **kwargs: Response(body, 'text/event-stream')).complete(case)
        self.assertFalse(result.complete)
        self.assertEqual(result.issue, 'stream_interrupted')

    def test_arbitrary_payload_subclasses_are_still_rejected(self):
        from relay_auditor.protocol import ProbeCase

        class OtherCase(ProbeCase):
            pass

        target = Target('https://relay.invalid/v1', 'synthetic', 'gpt-test', Protocol())
        with self.assertRaisesRegex(EndpointError, 'invalid_synthetic_case'):
            APIClient(target).complete(OtherCase('trace', 42, 'synthetic'))

    def test_complete_exam_uses_actual_serialization_and_response_parsing(self):
        paper = {case.prompt: case for case, _ in exam_cases('gpt', 120, 42)}
        requests = []

        def open_request(request, timeout):
            body = json.loads(request.data)
            case = paper[body['input'][0]['content']]
            requests.append(body)
            return Response(json.dumps({'output_text': json.dumps({'answer': case.expected}),
                                        'usage': {'input_tokens': 20, 'output_tokens': 10}}).encode())

        with tempfile.TemporaryDirectory() as directory:
            with Auditor(directory, client_factory=lambda target: APIClient(target, open_request)) as auditor:
                auditor.store.set_limits(200, 2_000_000)
                alias = auditor.configure('https://relay.invalid/v1', 'synthetic', 'gpt-test')
                preview = auditor.estimate(alias, 'capability_exam', 120, comparison='relay_only')
                from unittest.mock import patch
                with patch('relay_auditor.controller.secrets.randbelow', return_value=42):
                    result = auditor.run(alias, 'capability_exam', exam_plan_id=preview['exam_plan_id'])
                self.assertTrue(result['exam']['submitted'])
                self.assertEqual(result['capability_correct'], 120)
                self.assertEqual(len(requests), 120)
                self.assertEqual(auditor.store.budget()['held_requests'], 0)
