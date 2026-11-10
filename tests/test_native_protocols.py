import json
import unittest
from relay_auditor.protocol import Protocol,make_case
from relay_auditor.transport import APIClient,Target,EndpointError
from test_transport import Response


class NativeProtocolTests(unittest.TestCase):
    def test_anthropic_json_cache_accounting_and_headers(self):
        requests=[]
        def request(req,timeout):
            requests.append(req)
            return Response(b'{"content":[{"type":"thinking","thinking":"PRIVATE"},{"type":"text","text":"7"}],"stop_reason":"end_turn","usage":{"input_tokens":4,"cache_read_input_tokens":8,"cache_creation_input_tokens":2,"output_tokens":3}}')
        target=Target('https://relay.example/v1','SYNTHETIC','claude-test',Protocol(wire_api='anthropic'))
        result=APIClient(target,request).complete(make_case('digit',1))
        self.assertEqual(result.text,'7'); self.assertEqual(result.usage['input_tokens'],14)
        self.assertEqual(result.usage['total_tokens'],17)
        self.assertEqual(requests[0].get_header('X-api-key'),'SYNTHETIC')
        self.assertIsNone(requests[0].get_header('Authorization'))
        self.assertEqual(requests[0].full_url,'https://relay.example/v1/messages')

    def test_anthropic_stream_requires_stop_and_merges_partial_usage(self):
        events=[{'type':'message_start','message':{'usage':{'input_tokens':5,'output_tokens':0}}},
                {'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'PRIVATE'}},
                {'type':'content_block_delta','delta':{'type':'text_delta','text':'7'}},
                {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':2}}]
        def complete(rows):
            raw=''.join('data: '+json.dumps(x)+'\n\n' for x in rows).encode()
            return APIClient(Target('https://relay.example/v1','key','claude-test',Protocol(wire_api='anthropic',stream=True)),
                             lambda *a,**k:Response(raw,'text/event-stream')).complete(make_case('digit',1))
        self.assertFalse(complete(events).complete)
        result=complete(events+[{'type':'message_stop'}])
        self.assertTrue(result.complete); self.assertEqual(result.text,'7'); self.assertEqual(result.usage['total_tokens'],7)

    def test_gemini_key_in_header_and_reasoning_usage_is_subset(self):
        requests=[]
        def request(req,timeout):
            requests.append(req)
            return Response(b'{"candidates":[{"content":{"parts":[{"text":"PRIVATE","thought":true},{"text":"7"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2,"thoughtsTokenCount":3}}')
        result=APIClient(Target('https://relay.example/v1beta','SYNTHETIC','gemini-test',Protocol(wire_api='gemini')),request).complete(make_case('digit',1))
        self.assertEqual(result.text,'7'); self.assertEqual(result.usage['output_tokens'],5)
        self.assertEqual(result.usage['total_tokens'],10)
        self.assertNotIn('SYNTHETIC',requests[0].full_url)
        self.assertEqual(requests[0].get_header('X-goog-api-key'),'SYNTHETIC')

    def test_native_reference_hosts_are_fixed_by_protocol(self):
        for wire,url in [('anthropic','https://api.anthropic.com/v1'),('gemini','https://generativelanguage.googleapis.com/v1beta')]:
            self.assertEqual(Target(url,'key','test',Protocol(wire_api=wire),role='reference').base_url,url)
            with self.assertRaises(ValueError): Target('https://relay.example/v1','key','test',Protocol(wire_api=wire),role='reference')
            with self.assertRaises(ValueError): Target(url,'key','test',Protocol(wire_api=wire))

    def test_native_unsupported_effort_fails_before_sending(self):
        def forbidden(*a,**k): self.fail('network must not run')
        with self.assertRaises(EndpointError):
            APIClient(Target('https://relay.example/v1beta','key','gemini-test',Protocol(wire_api='gemini',reasoning_effort='xhigh')),forbidden).complete(make_case('digit',1))


if __name__=='__main__':unittest.main()
