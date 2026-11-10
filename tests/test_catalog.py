import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from relay_auditor.catalog import read_catalog


CONFIG = '''model="gpt-test"
model_provider="custom"
[model_providers.custom]
base_url="https://synthetic-relay.invalid/v1"
requires_openai_auth=true
experimental_bearer_token="SYNTHETIC-KEY"
wire_api="responses"
'''


class CatalogTests(unittest.TestCase):
    def test_cc_switch_is_read_through_copy_and_never_imports_official_login_for_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source'; output=root/'output'
            source.mkdir(); output.mkdir(); path=source/'cc-switch.db'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE providers(id TEXT, app_type TEXT, settings_config TEXT, category TEXT, meta TEXT, is_current INTEGER)')
            db.executemany('INSERT INTO providers VALUES(?,?,?,?,?,?)', [
                ('PRIVATE-OFFICIAL', 'codex', '{}', 'official', '{}', 0),
                ('PRIVATE-RELAY', 'codex', json.dumps({'config':CONFIG}), 'official', '{}', 1),
                ('PRIVATE-CLAUDE', 'claude', '{}', 'official', '{}', 0)])
            db.commit(); db.close()
            before=path.read_bytes()
            catalog=read_catalog('cc_switch', path, output)
            summary=catalog.summary()
            self.assertEqual([x['source_kind'] for x in summary], ['official_login', 'relay'])
            self.assertFalse(summary[0]['can_detect'])
            self.assertTrue(summary[1]['can_detect'])
            self.assertNotIn('PRIVATE', json.dumps(summary))
            self.assertNotIn('SYNTHETIC-KEY', repr(catalog))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(output.iterdir()), [])

    def test_codexplusplus_official_mixed_mode_is_still_relay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'source'/'settings.json'; path.parent.mkdir(); output=root/'output'; output.mkdir()
            path.write_text(json.dumps({'activeRelayId':'PRIVATE-ID', 'relayProfiles':[
                {'id':'PRIVATE-ID','name':'PRIVATE-NAME','relayMode':'official', 'officialMixApiKey':True,
                 'configContents':CONFIG, 'authContents':'{"tokens":{"access_token":"PRIVATE-LOGIN"}}'}]}),encoding='utf-8')
            catalog=read_catalog('codexplusplus',path,output)
            self.assertEqual(catalog.summary()[0]['source_kind'],'relay')
            self.assertEqual(catalog.summary()[0]['model'],'gpt-test')
            self.assertTrue(catalog.summary()[0]['current_selected'])
            spec=catalog.get('catalog-1')
            self.assertEqual(spec.api_key,'SYNTHETIC-KEY')
            self.assertNotIn('PRIVATE',json.dumps(catalog.summary()))

    def test_official_direct_api_is_not_official_login_or_a_relay_test_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'output'; output.mkdir(); path=root/'source'/'settings.json'; path.parent.mkdir()
            path.write_text(json.dumps({'relayProfiles':[{'id':'x','configContents':CONFIG.replace('synthetic-relay.invalid','api.openai.com')}]}),encoding='utf-8')
            row=read_catalog('codexplusplus',path,output).summary()[0]
            self.assertEqual(row['source_kind'],'official_api')
            self.assertFalse(row['can_detect'])

    def test_catalog_refuses_source_output_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'; path.write_text('{"relayProfiles":[]}',encoding='utf-8')
            with self.assertRaises(ValueError):
                read_catalog('codexplusplus',path,Path(directory))

    def test_pure_official_mode_ignores_stale_relay_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'source'/'settings.json'; path.parent.mkdir(); output=root/'output'; output.mkdir()
            path.write_text(json.dumps({'relayProfiles':[{'id':'x','relayMode':'official','officialMixApiKey':False,
                                                         'configContents':CONFIG}]}),encoding='utf-8')
            catalog=read_catalog('codexplusplus',path,output)
            self.assertEqual(catalog.summary()[0]['source_kind'],'official_login')
            self.assertFalse(catalog.summary()[0]['can_detect'])
            self.assertIsNone(catalog.get('catalog-1').api_key)

    def test_environment_auth_never_falls_back_to_retained_official_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'source'/'settings.json'; path.parent.mkdir(); output=root/'output'; output.mkdir()
            config=CONFIG.replace('experimental_bearer_token="SYNTHETIC-KEY"','env_key="SYNTHETIC_ENV"')
            path.write_text(json.dumps({'relayProfiles':[{'id':'x','relayMode':'pureApi','configContents':config,
                       'authContents':'{"OPENAI_API_KEY":"SYNTHETIC-OFFICIAL"}'}]}),encoding='utf-8')
            catalog=read_catalog('codexplusplus',path,output)
            self.assertFalse(catalog.summary()[0]['can_detect'])
            self.assertIsNone(catalog.get('catalog-1').api_key)

    def test_default_official_api_key_configuration_is_not_chatgpt_login(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'source'/'settings.json'; path.parent.mkdir(); output=root/'output'; output.mkdir()
            path.write_text(json.dumps({'relayProfiles':[{'id':'x','relayMode':'pureApi',
                 'configContents':'model_provider="openai"\nmodel="gpt-test"\n',
                 'authContents':'{"OPENAI_API_KEY":"SYNTHETIC-OFFICIAL"}'}]}),encoding='utf-8')
            catalog=read_catalog('codexplusplus',path,output)
            self.assertEqual(catalog.summary()[0]['source_kind'],'official_api')
            self.assertFalse(catalog.summary()[0]['can_detect'])


if __name__ == '__main__':
    unittest.main()
