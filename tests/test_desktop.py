import http.client
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class DesktopRuntimeTests(unittest.TestCase):
    def test_desktop_uses_private_user_data_and_cli_keeps_source_data(self):
        runtime = importlib.import_module('relay_auditor.runtime')
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                self.assertEqual(runtime.data_directory(desktop=True), Path(folder)/'Relay-Auditor')
            self.assertEqual(runtime.data_directory(), Path(__file__).resolve().parents[1]/'.relay-data')

    def test_frozen_worker_uses_fixed_sibling_executable_not_script_flags(self):
        runtime = importlib.import_module('relay_auditor.runtime')
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)/'Relay-Auditor.exe'
            worker = Path(folder)/'Relay-Auditor-Worker.exe'
            app.touch(); worker.touch()
            with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(app)):
                self.assertEqual(runtime.worker_command(), [str(worker)])
                worker.unlink()
                with self.assertRaises(ValueError):
                    runtime.worker_command()

    def test_unix_uses_platform_data_directory_and_fixed_suffixless_worker(self):
        from relay_auditor import runtime
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(Path, 'home', return_value=root):
                with patch.object(sys, 'platform', 'darwin'):
                    self.assertEqual(runtime.data_directory(desktop=True), root/'Library'/'Application Support'/'Relay-Auditor')
                with patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_DATA_HOME': str(root/'xdg')}):
                    self.assertEqual(runtime.data_directory(desktop=True), root/'xdg'/'Relay-Auditor')
                with patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_DATA_HOME': 'relative'}):
                    self.assertEqual(runtime.data_directory(desktop=True), root/'.local'/'share'/'Relay-Auditor')
            worker = root/'Relay-Auditor-Worker'
            worker.touch()
            for platform in ('darwin', 'linux'):
                with patch.object(sys, 'platform', platform), patch.object(sys, 'frozen', True, create=True), \
                     patch.object(sys, 'executable', str(root/'Relay-Auditor')):
                    self.assertEqual(runtime.worker_command(), [str(worker)])

    def test_unix_webkit_rules_match_only_the_current_session(self):
        import re
        from relay_auditor.desktop import LocalWindowPolicy
        policy = LocalWindowPolicy('http://127.0.0.1:9999/abc/', 'gtkwebkit2')
        self.assertIsNone(policy.initialized('gtkwebkit2'))
        self.assertFalse(policy.initialized('qtwebengine'))
        rules = json.loads(policy.content_rules())
        self.assertEqual(rules[0]['action']['type'], 'block')
        allowed = [rule['trigger']['url-filter'] for rule in rules[1:]]
        for url in ('http://127.0.0.1:9999/abc/state', 'data:,'):
            self.assertTrue(any(re.match(regex, url) for regex in allowed))
        for url in ('http://127.0.0.1:9999/other', 'http://127x0x0x1:9999/abc/state',
                    'https://other.invalid/', 'file:///tmp/local'):
            self.assertFalse(any(re.match(regex, url) for regex in allowed))

    def test_window_lifetime_stops_loopback_and_defaults_to_no_detection(self):
        desktop = importlib.import_module('relay_auditor.desktop')
        with tempfile.TemporaryDirectory() as folder:
            session = desktop.DesktopSession(Path(folder))
            session.start()
            port = session.server.server_port
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            connection.request('GET', session.server.session_path+'state')
            response = connection.getresponse()
            state = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(state['targets'], [])
            self.assertTrue(state['desktop'])
            connection.close()
            session.close(); session.close()
            self.assertTrue(session.service.stop_event.is_set())
            with self.assertRaises(OSError):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                connection.request('GET', '/')
            connection.close()

    def test_desktop_startup_errors_never_expose_original_exception(self):
        desktop = importlib.import_module('relay_auditor.desktop')
        messages = []
        with patch.object(desktop, 'load_webview', side_effect=RuntimeError('PRIVATE-KEY /private/path')):
            self.assertEqual(desktop.main(show_error=messages.append), 1)
        self.assertEqual(len(messages), 1)
        self.assertNotIn('PRIVATE', messages[0])
        self.assertNotIn('/private', messages[0])

    def test_native_catalog_cancel_and_import_do_not_return_private_paths(self):
        from relay_auditor.controller import Service
        from relay_auditor.storage import Store
        actions_module = importlib.import_module('relay_auditor.desktop_actions')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root/'source'/'settings.json'
            config.parent.mkdir()
            config.write_text(json.dumps({'relayProfiles':[{'id':'PRIVATE-ID','name':'PRIVATE-NAME',
                'relayMode':'pureApi','configContents':'model="model-a"\nmodel_provider="relay"\n[model_providers.relay]\nbase_url="https://relay.example/v1"',
                'authContents':'{"OPENAI_API_KEY":"PRIVATE-KEY"}'}]}), encoding='utf-8')
            store = Store(root/'output')
            service = Service(store)
            answers = iter([None, (str(config),)])
            actions = actions_module.DesktopActions(service, lambda kind, source: next(answers), lambda path: None, lambda: None)
            self.assertEqual(actions.dispatch('catalog', {'source':'codexplusplus'}), {'ok':True,'cancelled':True})
            result = actions.dispatch('catalog', {'source':'codexplusplus'})
            self.assertEqual(result, {'ok':True})
            self.assertEqual(service.catalog.summary()[0]['source_kind'], 'relay')
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertNotIn(str(root), json.dumps(result))
            self.assertEqual(service.snapshot()['targets'], [])
            store.close()

    def test_stopping_observer_terminates_its_own_inflight_worker(self):
        import time
        from relay_auditor.controller import Service
        from relay_auditor.observer import Observer
        from relay_auditor.storage import Store
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'source').mkdir()
            store = Store(root/'output')
            observer = Observer(Service(store), root/'source')
            with patch('relay_auditor.observer.worker_command', return_value=[sys.executable,'-c','import time; time.sleep(60)']):
                thread = threading.Thread(target=observer.refresh, daemon=True); thread.start()
                deadline = time.monotonic()+3
                while getattr(observer, 'process', None) is None and time.monotonic()<deadline:
                    time.sleep(0.01)
                observer.stop(); thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            store.close()

    def test_native_export_is_allowlisted_and_only_under_private_output(self):
        from relay_auditor.controller import Service
        from relay_auditor.storage import Store
        actions_module = importlib.import_module('relay_auditor.desktop_actions')
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        folder = temporary.name
        store = Store(folder); self.addCleanup(store.close)
        service = Service(store)
        service.configure('https://relay.example/v1','PRIVATE-KEY','model-a')
        opened = []
        actions = actions_module.DesktopActions(service, lambda *args: None, opened.append, lambda: None)
        self.assertEqual(actions.dispatch('export', {}), {'ok':True})
        files = list((Path(folder)/'exports').glob('*.json'))
        self.assertEqual(len(files), 1)
        content = files[0].read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE', content)
        self.assertNotIn('relay.example', content)
        self.assertEqual(json.loads(content)['targets'][0]['source_alias'], 'relay-1')
        self.assertEqual(opened, [Path(folder)/'exports'])

    def test_native_routes_require_same_origin_and_are_absent_in_browser_mode(self):
        from relay_auditor.controller import Service
        from relay_auditor.server import make_server
        from relay_auditor.storage import Store
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        store = Store(temporary.name); self.addCleanup(store.close)
        server = make_server(Service(store))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
        conn.request('POST', server.session_path+'desktop/export', '{}',
            {'Origin':origin,'Content-Type':'application/json','X-Relay-Request':'1'})
        response = conn.getresponse(); response.read()
        self.assertEqual(response.status,404); conn.close()

    def test_native_network_policy_allows_only_exact_session_assets(self):
        module = importlib.import_module('relay_auditor.desktop')
        policy = module.LocalWindowPolicy('http://127.0.0.1:9999/abc/')
        for url in ('http://127.0.0.1:9999/abc/', 'http://127.0.0.1:9999/abc/#history'):
            self.assertTrue(policy.allows_navigation(url))
        for url in ('https://example.com/', 'file:///C:/private', 'http://127.0.0.1:9999/abc/state'):
            self.assertFalse(policy.allows_navigation(url))
        self.assertTrue(policy.allows_resource('http://127.0.0.1:9999/abc/state'))
        self.assertFalse(policy.allows_resource('https://example.com/'))
        self.assertFalse(policy.allows_resource('http://127.0.0.1:9999/other'))

    def test_missing_webview2_rejects_library_ie_fallback(self):
        from relay_auditor.desktop import LocalWindowPolicy
        policy = LocalWindowPolicy('http://127.0.0.1:9999/abc/')
        self.assertFalse(policy.initialized('mshtml'))
        self.assertTrue(policy.failed)
        good = LocalWindowPolicy('http://127.0.0.1:9999/abc/')
        self.assertIsNone(good.initialized('edgechromium'))
        self.assertFalse(good.failed)

    def test_native_initialization_failure_is_carried_out_of_callback(self):
        from relay_auditor.desktop import LocalWindowPolicy
        class Event:
            def __init__(self):
                self.handlers = []
            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self
        control = SimpleNamespace(NavigationStarting=Event(),CoreWebView2InitializationCompleted=Event())
        shown, destroyed = threading.Event(), threading.Event(); shown.set()
        window = SimpleNamespace(native=SimpleNamespace(browser=SimpleNamespace(webview=control)),
                                 events=SimpleNamespace(shown=shown),destroy=destroyed.set)
        policy = LocalWindowPolicy('http://127.0.0.1:9999/abc/')
        policy.install(window)
        control.CoreWebView2InitializationCompleted.handlers[0](None,SimpleNamespace(IsSuccess=False))
        self.assertTrue(destroyed.wait(2))
        self.assertTrue(policy.failed)

    def test_native_http_actions_enforce_origin_and_hide_errors(self):
        from relay_auditor.controller import Service
        from relay_auditor.server import make_server
        from relay_auditor.storage import Store
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        store = Store(temporary.name); self.addCleanup(store.close)
        class DialogFailure:
            def dispatch(self, route, body):
                raise RuntimeError('PRIVATE-PATH PRIVATE-KEY')
        server = make_server(Service(store), desktop=DialogFailure())
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        for requested_origin, status in [('https://other.invalid',403),(origin,500)]:
            conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            conn.request('POST',server.session_path+'desktop/catalog','{"source":"cc_switch"}',
                {'Origin':requested_origin,'Content-Type':'application/json','X-Relay-Request':'1'})
            response = conn.getresponse(); content = response.read()
            self.assertEqual(response.status,status)
            self.assertNotIn(b'PRIVATE',content); conn.close()

    def test_native_reminder_only_flashes_new_anomalies_when_enabled(self):
        from relay_auditor.controller import Service
        from relay_auditor.storage import Store
        from relay_auditor.desktop_actions import DesktopActions
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        store = Store(temporary.name); self.addCleanup(store.close)
        service = Service(store); flashes = []
        actions = DesktopActions(service,lambda *args:None,lambda path:None,lambda:flashes.append(1))
        service.notification_id = 1
        actions.dispatch('notify', {})
        self.assertEqual(flashes, [])
        actions.dispatch('notifications', {'enabled':True})
        actions.dispatch('notify', {})
        self.assertEqual(flashes, [])
        service.notification_id = 2
        actions.dispatch('notify', {}); actions.dispatch('notify', {})
        self.assertEqual(flashes, [1])
        actions.dispatch('notifications', {'enabled':False})
        service.notification_id = 3; actions.dispatch('notify', {})
        self.assertEqual(flashes, [1])


if __name__ == '__main__':
    unittest.main()
