import argparse
import getpass
import json
import sys
import webbrowser
from .prompts import hidden

from .controller import Service
from .protocol import Protocol
from .server import make_server
from .storage import Store
from .runtime import data_directory
from .core import Auditor
from .protocol import OFFICIAL_ENDPOINTS,REASONING_EFFORTS


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error echoes unknown command arguments.
        raise ValueError('invalid_arguments')


def main(argv=None):
    parser = Parser(description='Experimental relay model auditor; official login is never probed.')
    parser.add_argument('command', nargs='?', default='serve',
                        choices=('serve','check','baseline','audit','capability','history','quality','quality-audit','context','reasoning','assessment',
                                 'support','profiles','suites','estimate','demo','calibration-simulate','calibration-init','calibration-collect','calibration-report'))
    parser.add_argument('--no-open', action='store_true', help='Do not open a browser automatically')
    parser.add_argument('--samples', type=int, help='Samples per probe / capability pairs')
    parser.add_argument('--seed',type=int,help='Replayable synthetic suite seed, 0 <= seed < 2**31')
    parser.add_argument('--request-limit', type=int, help='Explicit daily request limit')
    parser.add_argument('--token-limit', type=int, help='Explicit daily estimated token budget')
    parser.add_argument('--wire-api', choices=tuple(OFFICIAL_ENDPOINTS), default='responses')
    parser.add_argument('--stream', action='store_true', help='Explicitly request streaming responses')
    parser.add_argument('--reasoning-effort',choices=REASONING_EFFORTS)
    parser.add_argument('--target',help='Saved relay-N alias, never a credential')
    parser.add_argument('--save-key',action='store_true',help='Opt in to the owned OS vault item')
    parser.add_argument('--mode',choices=('screen','quality','quality_audit','baseline','identity_audit','capability_audit','context','reasoning','assessment'),default='quality')
    parser.add_argument('--primary-model'); parser.add_argument('--alternative-model')
    parser.add_argument('--trials',type=int,default=100); parser.add_argument('--study-id')
    parser.add_argument('--study-scope',choices=('primary','extended'),default='primary')
    parser.add_argument('--calibration-audit-index',type=int,default=1)
    parser.add_argument('--phase',choices=('pilot','validation'),default='pilot')
    parser.add_argument('--scenario',choices=('healthy','substitution','reasoning_changed','context_truncated','mixed_10','mixed_30','mixed_50'),default='healthy')
    parser.add_argument('--trial',type=int,default=0)
    store = service = server = None
    auditor=None
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as exit_code:
            return exit_code.code
        if args.samples is not None and not 1 <= args.samples <= 200:
            raise ValueError('invalid_samples')
        if args.command=='suites':
            from .suites import SUITES
            print(json.dumps(SUITES)); return 0
        if args.command=='demo':
            import tempfile
            from .demo import snapshot
            with tempfile.TemporaryDirectory() as directory: print(json.dumps(snapshot(directory)))
            return 0
        if args.command=='calibration-simulate':
            from .simulation import simulate
            options = {'seed': args.seed} if args.seed is not None else {}
            print(json.dumps(simulate(trials=args.trials, audit_index=args.calibration_audit_index, **options), allow_nan=False))
            return 0
        if args.command.startswith('calibration-'):
            from .calibration_cli import command
            store=Store(data_directory())
            try:
                print(json.dumps(command(args,store)))
            finally:
                store.close()
            return 0
        auditor=Auditor(data_directory(),persist_settings=True)
        store,service=auditor.store,auditor.service
        if args.request_limit is not None or args.token_limit is not None:
            before = store.budget()
            store.set_limits(args.request_limit if args.request_limit is not None else before['request_limit'],
                             args.token_limit if args.token_limit is not None else before['token_limit'])
        if args.command == 'history':
            print(json.dumps({'schema_version': 2, 'history': service.snapshot()['history'], 'budget': store.budget()}, ensure_ascii=False))
            return 0
        if args.command in ('support','profiles'):
            print(json.dumps(service.snapshot()['support' if args.command=='support' else 'targets'],ensure_ascii=False)); return 0
        if args.command == 'serve':
            server = make_server(service)
            service.start()
            if not args.no_open:
                webbrowser.open(server.local_url)
            # Only this ephemeral loopback URL; it contains no upstream/private configuration.
            print('本机检测页面：' + server.local_url, flush=True)
            print('检测默认关闭。关闭此窗口停止服务。', flush=True)
            server.serve_forever()
            return 0
        # Endpoint and secrets are never accepted on the command line or echoed.
        if args.target:
            if args.target not in service.monitors: raise ValueError('unknown_target')
            alias=args.target
            if args.command!='estimate' and not service.monitors[alias].credential_ready:
                service.credentials(alias,hidden('中转专用 API Key（隐藏输入）：'),reference_key=hidden('独立官方参考 Key（可留空）：') or None,save_credentials=args.save_key)
        else:
            endpoint=hidden('中转 API 基础地址（隐藏输入）：'); key=hidden('中转专用 API Key（隐藏输入）：')
            model=input('声明模型名称：').strip(); reference=hidden('独立官方 API Key（可留空，隐藏输入）：')
            reference_model=input('官方参考模型（留空同声明模型）：').strip() if reference else None
            alias=service.configure(endpoint,key,model,Protocol(wire_api=args.wire_api,stream=args.stream,reasoning_effort=args.reasoning_effort),reference_key=reference or None,reference_model=reference_model or None,save_credentials=args.save_key)
        if args.command=='estimate':
            print(json.dumps(service.estimate(alias,args.mode,args.samples))); return 0
        mode={'check':'screen','baseline':'baseline','audit':'identity_audit','capability':'capability_audit','quality':'quality','quality-audit':'quality_audit','context':'context','reasoning':'reasoning','assessment':'assessment'}[args.command]
        result = service.run(alias, mode, args.samples,seed=args.seed)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['status'] == 'ok' else 1
    except KeyboardInterrupt:
        print('已停止后续请求。')
        return 0
    except (ValueError, TypeError, EOFError):
        print('invalid_arguments_or_configuration', file=sys.stderr)
        return 2
    except Exception:
        print('local_error', file=sys.stderr)
        return 1
    finally:
        if service:
            service.stop()
        if server:
            server.server_close()
        if auditor: auditor.close()
