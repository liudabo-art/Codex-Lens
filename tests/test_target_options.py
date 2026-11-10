import importlib
import importlib.util
import io
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
import threading
import time
from unittest.mock import patch

from relay_auditor.controller import Service
from relay_auditor.protocol import Protocol, make_case
from relay_auditor.storage import Store
from relay_auditor.transport import APIClient, Target
from test_transport import Response
from test_service import FakeClient


class TargetOptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root/'output'); self.addCleanup(self.store.close)
        self.service = Service(self.store, client_factory=FakeClient)

    @unittest.skipUnless(importlib.util.find_spec('webview'), 'desktop dependency only in isolated builder')
    def test_native_filters_are_accepted_by_actual_desktop_library(self):
        from webview.util import parse_file_type
        from relay_auditor.desktop import catalog_dialog_types
        self.assertEqual(parse_file_type(catalog_dialog_types('cc_switch')[0])[1], '*.db')
        self.assertEqual(parse_file_type(catalog_dialog_types('codexplusplus')[0])[1], '*.json')

    def test_one_click_catalog_finds_only_known_locations(self):
        from relay_auditor.catalog import locate_catalog
        file = self.root/'.codex-session-delete'/'settings.json'; file.parent.mkdir()
        file.write_text('{"relayProfiles":[]}', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(locate_catalog('codexplusplus', home=self.root), file)
            with self.assertRaises(ValueError): locate_catalog('cc_switch', home=self.root)

    def test_configured_model_list_and_reasoning_are_imported(self):
        from relay_auditor.catalog import read_catalog
        file = self.root/'source'/'settings.json'; file.parent.mkdir()
        config = 'model="gpt-test"\nmodel_provider="relay"\nmodel_reasoning_effort="xhigh"\n[model_providers.relay]\nbase_url="https://relay.example/v1"\nexperimental_bearer_token="PRIVATE-KEY"'
        file.write_text(json.dumps({'relayProfiles':[{'id':'private','configContents':config,
                         'modelList':'gpt-test\ngpt-second\nhttps://private.invalid/key'}]}),encoding='utf-8')
        spec = read_catalog('codexplusplus',file,self.store.directory).get('catalog-1')
        self.assertEqual(spec.models, ['gpt-test','gpt-second'])
        self.assertEqual(spec.reasoning_effort, 'xhigh')

    def test_user_names_stay_in_ui_only_and_settings_reset_old_result(self):
        alias = self.service.configure('https://relay.example/v1','PRIVATE-KEY','gpt-test',
                                       display_name='我的测试', models=['gpt-test','gpt-second'])
        self.service.monitors[alias].last_result = {'identity_state':'screening_consistent'}
        self.service.control(alias,enabled=True)
        self.service.update_target(alias, display_name='我的新测试',model='gpt-second',reasoning_effort='xhigh')
        monitor = self.service.monitors[alias]
        self.assertFalse(monitor.enabled)
        self.assertIsNone(monitor.last_result)
        self.assertEqual(monitor.target.protocol.reasoning_effort,'xhigh')
        self.assertEqual(self.service.ui_snapshot()['display_names'][alias], '我的新测试')
        self.assertNotIn('我的新测试',json.dumps(self.service.snapshot(),ensure_ascii=False))
        self.assertEqual(self.service.ui_snapshot()['model_choices'][alias], ['gpt-test','gpt-second'])

    def test_failed_target_change_is_atomic(self):
        alias = self.service.configure('https://relay.example/v1','key','gpt-test')
        with self.assertRaises(ValueError):
            self.service.update_target(alias,display_name='changed',model='https://private.invalid',reasoning_effort='high')
        self.assertEqual(self.service.monitors[alias].target.model,'gpt-test')

    def test_default_reference_follows_changed_model_but_explicit_reference_is_preserved(self):
        for explicit in (None,'reference-fixed'):
            alias = self.service.configure('https://relay.example/v1','key','gpt-test',reference_key='reference-key',reference_model=explicit)
            self.service.update_target(alias,display_name='测试',model='gpt-second',reasoning_effort='high')
            monitor = self.service.monitors[alias]
            self.assertEqual(monitor.reference.model,explicit or 'gpt-second')
            self.assertEqual(monitor.reference_model,explicit or 'gpt-second')

    def test_remote_models_are_get_only_filtered_and_deduplicated(self):
        captured=[]
        def request(req,timeout):
            captured.append(req)
            return Response(b'{"data":[{"id":"gpt-test"},{"id":"gpt-test"},{"id":"https://private.invalid/key"},{"id":"gpt-second"}]}')
        client=APIClient(Target('https://relay.example/v1','PRIVATE-KEY','gpt-test',Protocol()),request)
        self.assertEqual(client.list_models(),['gpt-test','gpt-second'])
        self.assertEqual(captured[0].get_method(),'GET')
        self.assertEqual(captured[0].full_url,'https://relay.example/v1/models')
        self.assertIsNone(captured[0].data)

    def test_extended_reasoning_is_sent_in_both_protocols(self):
        for wire in ('responses','chat'):
            for effort in ('none','minimal','xhigh','max'):
                captured=[]
                def request(req,timeout):
                    captured.append(json.loads(req.data)); return Response(b'{"output_text":"7"}')
                APIClient(Target('https://relay.example/v1','key','gpt-test',Protocol(wire_api=wire,reasoning_effort=effort)),request).complete(make_case('digit',0))
                self.assertEqual(captured[0].get('reasoning',{}).get('effort') if wire=='responses' else captured[0]['reasoning_effort'],effort)

    def test_http_one_click_import_and_explicit_screen_use_selected_parameters(self):
        from relay_auditor.desktop_actions import DesktopActions
        from relay_auditor.profiles import Profiles
        from relay_auditor.server import make_server
        from test_sdk_exports import FakeVault

        vault = FakeVault()
        profiles = Profiles(self.root/'profiles', vault=vault)
        self.service = Service(self.store, client_factory=FakeClient, profiles=profiles)
        file = self.root/'source'/'settings.json'; file.parent.mkdir()
        config = 'model="gpt-test"\nmodel_provider="relay"\nmodel_reasoning_effort="high"\n[model_providers.relay]\nbase_url="https://relay.example/v1"\nexperimental_bearer_token="PRIVATE-KEY"'
        file.write_text(json.dumps({'relayProfiles':[{'id':'private','configContents':config,'modelList':'gpt-test\ngpt-second'},
                                                    {'id':'official','relayMode':'official'}]}),encoding='utf-8')
        actions=DesktopActions(self.service,lambda *args:None,lambda path:None,lambda:None)
        server=make_server(self.service,desktop=actions)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin=f'http://127.0.0.1:{server.server_port}'
        def post(route,body):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('POST',server.session_path+route,json.dumps(body),{'Origin':origin,'Content-Type':'application/json','X-Relay-Request':'1'})
            response=conn.getresponse(); result=json.loads(response.read()); conn.close()
            return response.status,result
        with patch('relay_auditor.desktop_actions.locate_catalog',return_value=file):
            self.assertEqual(post('desktop/catalog',{'source':'codexplusplus','auto':True})[0],200)
        catalog_id=self.service.catalog.catalog_id
        status,result=post('catalog_select',{'catalog_id':catalog_id,'source_alias':'catalog-1','model':'gpt-second',
                                            'display_name':'合成测试','reasoning_effort':'xhigh','run_now':True})
        self.assertEqual(status,200)
        deadline=time.monotonic()+3
        while self.service.busy and time.monotonic()<deadline: time.sleep(0.01)
        monitor=self.service.monitors[result['source_alias']]
        self.assertEqual(monitor.target.model,'gpt-second')
        self.assertEqual(monitor.target.protocol.reasoning_effort,'xhigh')
        self.assertFalse(monitor.enabled)
        self.assertEqual(self.store.budget()['requests'],3)
        self.assertNotIn('合成测试',json.dumps(self.store.history(),ensure_ascii=False))
        self.assertEqual(post('catalog_select',{'catalog_id':catalog_id,'source_alias':'catalog-2','model':'gpt-test','run_now':True})[0],400)
        status, remembered = post('catalog_select', {'catalog_id':catalog_id, 'source_alias':'catalog-1',
                                                       'model':'gpt-second', 'display_name':'合成保存导入',
                                                       'save_credentials':True})
        self.assertEqual(status,200)
        restored = Service(self.store, client_factory=FakeClient, profiles=profiles)
        self.assertFalse(restored.monitors[result['source_alias']].credential_ready)
        unlocked = restored.monitors[remembered['source_alias']]
        self.assertTrue(unlocked.credential_ready)
        self.assertFalse(unlocked.enabled)
        self.assertEqual(unlocked.target.api_key, 'PRIVATE-KEY')
        self.assertIsNone(vault.read(monitor.target_id))
        self.assertNotIn('PRIVATE-KEY', profiles.path.read_text(encoding='utf-8'))
        self.assertNotIn('PRIVATE-KEY', json.dumps(restored.ui_snapshot()))
        self.assertEqual(self.store.budget()['requests'],3)

    def test_reference_model_list_uses_only_fixed_official_endpoint_and_reference_key(self):
        from relay_auditor.server import make_server
        server=make_server(self.service)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        targets=[]
        def list_models(client):
            targets.append(client.target); return ['official-test']
        origin=f'http://127.0.0.1:{server.server_port}'
        class ListingClient:
            def __init__(self,target): self.target=target
        ListingClient.list_models=list_models
        with patch.object(self.service,'client_factory',ListingClient):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('POST',server.session_path+'models',json.dumps({'role':'reference','reference_key':'reference-only',
                         'base_url':'https://relay.example/v1','api_key':'relay-only'}),
                         {'Origin':origin,'Content-Type':'application/json','X-Relay-Request':'1'})
            response=conn.getresponse(); body=json.loads(response.read()); conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(body['models'],['official-test'])
        self.assertEqual(targets[0].role,'reference')
        self.assertEqual(targets[0].base_url,'https://api.openai.com/v1')
        self.assertEqual(targets[0].api_key,'reference-only')


if __name__ == '__main__': unittest.main()
