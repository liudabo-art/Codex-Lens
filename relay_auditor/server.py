"""Same-origin, random-path loopback UI; no endpoint/key echo or request logging."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets

from .observer import Observer
from .catalog import read_catalog
from .protocol import Protocol,OFFICIAL_ENDPOINTS
from .transport import APIClient, Target, EndpointError
from .planning import MODES
from .families import family_for, REFERENCE_FAMILY


def make_server(service, *, desktop=None):
    session_path = '/' + secrets.token_urlsafe(32) + '/'
    assets = Path(__file__).with_name('web')
    observers = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle(self):
            self.connection.settimeout(10)
            super().handle()

        def reply(self, code, payload=b'', mime='application/json; charset=utf-8'):
            if not isinstance(payload, bytes):
                payload = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (OSError, TimeoutError):
                pass

        def authorized(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                    and self.path.startswith(session_path)
                    and self.headers.get('Origin') in (None, origin))

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'ok': False})
            route = self.path[len(session_path):]
            if route == 'state':
                return self.reply(200, service.ui_snapshot() | {'desktop': desktop is not None})
            if route == 'assessment':
                return self.reply(200, service.snapshot())
            if route == 'usage':
                return self.reply(200, service.usage_snapshot())
            if route=='report':
                from .exporting import html_report
                return self.reply(200,html_report(service.snapshot()).encode('utf-8'),'text/html; charset=utf-8')
            files = {'': ('index.html', 'text/html; charset=utf-8'),
                     'app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     'styles.css': ('styles.css', 'text/css; charset=utf-8')}
            if route not in files:
                return self.reply(404, {'ok': False})
            filename, mime = files[route]
            try:
                self.reply(200, (assets/filename).read_bytes(), mime)
            except OSError:
                self.reply(500, {'ok': False})

        def do_POST(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if (not self.authorized() or self.headers.get('Origin') != origin
                    or self.headers.get('X-Relay-Request') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or self.headers.get('Transfer-Encoding')):
                return self.reply(403, {'ok': False})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    return self.reply(413, {'ok': False})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('invalid_body')
                route = self.path[len(session_path):]
                if route.startswith('desktop/'):
                    if desktop is None:
                        return self.reply(404, {'ok': False})
                    return self.reply(200, desktop.dispatch(route[len('desktop/'):], body))
                if route == 'configure':
                    protocol = Protocol(wire_api=body.get('wire_api', 'responses'),
                                        max_output_tokens=body.get('max_output_tokens', 2048),
                                        reasoning_effort=body.get('reasoning_effort') or None,
                                        temperature=body.get('temperature'), stream=body.get('stream', False))
                    alias = service.configure(body['base_url'], body['api_key'], body['model'], protocol,
                                              reference_key=body.get('reference_key'), reference_model=body.get('reference_model'),
                                              display_name=body.get('display_name'), models=body.get('models'),save_credentials=body.get('save_credentials',False))
                    return self.reply(200, {'ok': True, 'source_alias': alias})
                if route=='credentials':
                    service.credentials(body['source_alias'],body.get('api_key'),reference_key=body.get('reference_key'),save_credentials=body.get('save_credentials',False))
                    return self.reply(200,{'ok':True})
                if route == 'official_reference':
                    matched = service.set_official_reference(body['target_id'], body['preset_id'], body['api_key'],
                                                             save_credentials=body.get('save_credentials', False))
                    return self.reply(200, {'ok': True, **matched})
                if route=='estimate':
                    return self.reply(200,{'ok':True,**service.estimate(body['source_alias'],body.get('mode','quality'),body.get('samples'),body.get('prices'))})
                if route=='cancel':
                    service.cancel(body.get('job_id')); return self.reply(200,{'ok':True})
                if route == 'target_options':
                    service.update_target(body['source_alias'],display_name=body['display_name'],model=body['model'],
                                          reasoning_effort=body.get('reasoning_effort'),wire_api=body.get('wire_api'))
                    return self.reply(200, {'ok': True})
                if route == 'models':
                    with service.lock:
                        if body.get('role') == 'reference':
                            protocol=Protocol(wire_api=body.get('wire_api','responses'))
                            declared = body.get('claimed_model')
                            if isinstance(declared, str) and family_for(declared) not in ('unknown', REFERENCE_FAMILY[protocol.wire_api]):
                                raise ValueError('reference_provider_mismatch')
                            target = Target(OFFICIAL_ENDPOINTS[protocol.wire_api],body.get('reference_key'),'model-discovery',protocol,role='reference')
                        elif body.get('catalog_id'):
                            if not service.catalog or body['catalog_id'] != service.catalog.catalog_id:
                                raise ValueError('catalog_changed')
                            spec = service.catalog.get(body['source_alias'])
                            if spec.source_kind != 'relay' or not spec.api_key:
                                raise ValueError('only_relay_can_be_detected')
                            target = Target(spec.base_url,spec.api_key,spec.model or 'model-discovery',Protocol(wire_api=spec.wire_api))
                        elif body.get('source_alias'):
                            target = service.target_for(body['source_alias'])
                        else:
                            target = Target(body['base_url'],body['api_key'],'model-discovery',Protocol(wire_api=body.get('wire_api','responses')))
                    models = service.client_factory(target).list_models()
                    with service.lock:
                        if body.get('role') != 'reference' and body.get('source_alias') in service.monitors:
                            service.monitors[body['source_alias']].models = models or [target.model]
                    return self.reply(200, {'ok':True,'models':models})
                if route == 'catalog':
                    catalog = read_catalog(body['source'], body['path'], service.store.directory)
                    with service.lock:
                        service.catalog, service.catalog_source = catalog, body['source']
                    return self.reply(200, {'ok': True})
                if route == 'catalog_select':
                    with service.lock:
                        if not service.catalog:
                            raise ValueError('catalog_missing')
                        if body.get('catalog_id') != service.catalog.catalog_id:
                            raise ValueError('catalog_changed')
                        spec = service.catalog.get(body['source_alias'])
                        if spec.source_kind != 'relay' or not spec.api_key:
                            raise ValueError('only_relay_can_be_detected')
                        alias = service.configure(spec.base_url, spec.api_key, body.get('model') or spec.model,
                                                  Protocol(wire_api=spec.wire_api,
                                                           reasoning_effort=(body.get('reasoning_effort') or None) if 'reasoning_effort' in body else spec.reasoning_effort),
                                                  reference_key=body.get('reference_key'), reference_model=body.get('reference_model'),
                                                  display_name=body.get('display_name'), models=spec.models,save_credentials=body.get('save_credentials',False))
                        if body.get('run_now') is True:
                            service.submit(alias, 'screen')
                    return self.reply(200, {'ok': True, 'source_alias': alias})
                if route == 'target_delete':
                    try:
                        service.delete_target(body.get('target_id'))
                    except ValueError as error:
                        code = str(error)
                        if code in ('target_running','unknown_target','profiles_unavailable','vault_unavailable','target_delete_rollback_failed'):
                            return self.reply(400, {'ok': False, 'error': code})
                        raise
                    return self.reply(200, {'ok': True})
                if route == 'control':
                    service.control(body['source_alias'], **{k: body[k] for k in ('enabled', 'interval_seconds', 'active_only') if k in body})
                elif route == 'run':
                    mode = body.get('mode', 'screen')
                    if mode not in MODES:
                        raise ValueError('invalid_mode')
                    samples = body.get('samples')
                    if samples is not None and (type(samples) is not int or not 1 <= samples <= 200):
                        raise ValueError('invalid_samples')
                    job_id=service.submit(body['source_alias'],mode,samples,expected_requests=body.get('expected_requests'),
                                          review_of=body.get('review_of'))
                    return self.reply(200,{'ok':True,'job_id':job_id})
                elif route == 'budget':
                    service.store.set_limits(body['request_limit'], body['token_limit'])
                elif route == 'active':
                    service.mark_active(body['source_alias'])
                elif route == 'observe':
                    observer = Observer(service, body['home'])
                    for previous in observers:
                        previous.stop()
                    observers.clear()
                    observers.append(observer)
                    observer.start()
                else:
                    return self.reply(404, {'ok': False})
                self.reply(200, {'ok': True})
            except EndpointError as error:
                self.reply(400, {'ok':False,'error':str(error) if str(error) in ('authentication_failed','models_unavailable','network_error','invalid_response','redirect_blocked','response_too_large','unsupported_parameters','rate_limited','http_error','remote_error','reference_required','reference_model_unavailable','official_direct') else 'local_error'})
            except (ValueError, TypeError, KeyError) as error:
                code = str(error)
                self.reply(400, {'ok': False, 'error':code if code in (
                    'catalog_not_found','unsupported_schema','source_unavailable','dialog_busy','credential_required',
                    'vault_unavailable','profiles_unavailable','queue_full','reference_required','credential_too_large_for_vault',
                    'reference_provider_mismatch','official_direct','busy','invalid_endpoint','invalid_model','invalid_samples',
                    'assessment_changed','invalid_reference_preset','reference_model_mismatch','reference_model_unavailable','reference_model_retired',
                    'reference_settings_mismatch','reference_changed','target_not_found','reference_use_panel','invalid_credential'
                ) else 'invalid_request_or_busy'})
            except Exception:
                self.reply(500, {'ok': False, 'error': 'local_error'})

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass

        def server_close(self):
            for observer in observers:
                observer.stop()
            super().server_close()

    server = Server(('127.0.0.1', 0), Handler)
    server.session_path = session_path
    server.local_url = f'http://127.0.0.1:{server.server_port}' + session_path
    return server
