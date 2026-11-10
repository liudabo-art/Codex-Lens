"""Fixed offline worker. Private source information never leaves this process."""
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    try:
        from datetime import datetime, timezone
        import tomllib
        from relay_auditor.vendor.safety import checked_local_path, validate_output, install_guard
        from relay_auditor.vendor.sessions import scan_sessions
        from relay_auditor.accounting import group_usage
        payload = json.loads(sys.stdin.buffer.read(100000))
        home = checked_local_path(payload['home'])
        output = validate_output(Path(payload['output']), home)
        install_guard(output)
        report = scan_sessions(home)
        turns = report.get('turns', [])
        summary = {'local_status': 'ok', 'source_kind': 'unknown',
                   'observed_local_tokens': sum(t.get('total_tokens', 0) for t in turns),
                   'observed_local_responses': sum(t.get('request_count', 0) for t in turns),
                   'source_attribution': 'unknown_historical_route',
                   'warning_count': len(report.get('warnings', []))}
        # This adapter has no request-scoped routing/authentication evidence.
        # Every historic turn therefore remains unknown; never infer from auth.json.
        summary['groups'] = group_usage(turns)
        # Current configuration is only an activity hint, never historical attribution.
        providers = {}
        try:
            config = tomllib.loads(checked_local_path(home/'config.toml').read_text(encoding='utf-8-sig'))
            providers = config.get('model_providers', {})
        except (ValueError, OSError):
            pass
        now = datetime.now(timezone.utc)
        sessions = {s['id']: s for s in report.get('sessions', [])}
        active_providers = set()
        for turn in turns:
            if not turn.get('total_tokens'):
                continue
            try:
                when = datetime.fromisoformat((turn.get('ended_at') or turn.get('started_at') or '').replace('Z', '+00:00'))
                if when.tzinfo is None or not 0 <= (now-when).total_seconds() <= 1800:
                    continue
            except (ValueError, TypeError):
                continue
            provider = sessions.get(turn.get('session_id'), {}).get('model_provider')
            if provider:
                active_providers.add(provider)
        aliases = []
        for target in payload.get('targets', []):
            if not isinstance(target, dict):
                continue
            for provider in active_providers:
                item = providers.get(provider)
                if isinstance(item, dict) and str(item.get('base_url', '')).rstrip('/') == target.get('base_url', '').rstrip('/'):
                    alias = target.get('source_alias')
                    if isinstance(alias, str) and __import__('re').fullmatch(r'relay-[0-9]+', alias):
                        aliases.append(alias)
        # No provider names, source paths, source IDs, warnings, content or raw records.
        print(json.dumps({'usage': summary, 'active_aliases': sorted(set(aliases))}, separators=(',', ':')))
        return 0
    except Exception:
        print('{"usage":{"local_status":"unavailable","source_kind":"unknown"},"active_aliases":[]}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
