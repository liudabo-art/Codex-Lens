"""Real frozen offline worker smoke; synthetic inputs only, fixed summaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def smoke(bundle):
    if sys.platform == 'darwin':
        worker = bundle/'Contents/MacOS/Relay-Auditor-Worker'
        resources = bundle/'Contents/Resources'
    else:
        worker = bundle/('Relay-Auditor-Worker.exe' if os.name == 'nt' else 'Relay-Auditor-Worker')
        resources = bundle/'_internal'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve(); home = root/'source'; output = root/'output'
        (home/'sessions').mkdir(parents=True); output.mkdir()
        rows = [{'type':'session_meta','payload':{'id':'PRIVATE-SYNTHETIC'}},
                {'type':'turn_context','payload':{'turn_id':'PRIVATE-TURN','model':'model-a'}},
                {'type':'token_usage_record','payload':{'response_id':'PRIVATE-RESPONSE','thread_id':'PRIVATE-SYNTHETIC',
                 'turn_id':'PRIVATE-TURN','usage':{'input_tokens':10,'output_tokens':5}}}]
        source = home/'sessions'/'fixture.jsonl'
        content = '\n'.join(json.dumps(row) for row in rows)+'\n'
        source.write_text(content, encoding='utf-8')
        result = subprocess.run([str(worker)],
            input=json.dumps({'home':str(home),'output':str(output),'targets':[]}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode or result.stderr or b'PRIVATE' in result.stdout:
            raise ValueError('worker_boundary_failed')
        body = json.loads(result.stdout)
        if body['usage']['observed_local_tokens'] != 15 or source.read_text(encoding='utf-8') != content:
            raise ValueError('worker_accounting_failed')
        if not (resources/'relay_auditor/web/index.html').is_file() or not (resources/'assets/codex-lens.png').is_file():
            raise ValueError('ui_resource_missing')
        print('frozen_worker_synthetic_smoke_passed')


if __name__ == '__main__':
    try:
        smoke(Path(sys.argv[1]))
    except Exception:
        print('frozen_smoke_failed', file=sys.stderr)
        raise SystemExit(1)
