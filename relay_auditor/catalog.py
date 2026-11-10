"""Read-only provider discovery; configuration is not a historical usage ledger.

CC Switch schema and Codex++ settings are independently adapted, not imported code.
Keys and original identifiers never leave the runtime catalog or enter its summary.
"""
from dataclasses import dataclass, field
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import tomllib
import uuid
from urllib.parse import urlsplit

from .protocol import MODEL_PATTERN, REASONING_EFFORTS, OFFICIAL_ENDPOINTS
from .models import model_choices
from .storage import checked_path


@dataclass(repr=False)
class ProviderSpec:
    source_kind: str
    model: str | None
    wire_api: str
    current_selected: bool = False
    base_url: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)
    models: list = field(default_factory=list)
    reasoning_effort: str | None = None

    def __repr__(self):
        return '<ProviderSpec: private configuration>'


class Catalog:
    def __init__(self, specs):
        self.catalog_id = uuid.uuid4().hex
        self._specs = {f'catalog-{i+1}': spec for i, spec in enumerate(specs)}

    def __repr__(self):
        return '<Catalog: private runtime provider directory>'

    def get(self, alias):
        return self._specs[alias]

    def summary(self):
        return [{'source_alias': alias, 'source_kind': spec.source_kind, 'model': spec.model,
                 'current_selected': spec.current_selected, 'can_detect': spec.source_kind == 'relay'
                 and bool(spec.api_key), 'provenance_level': 'configuration_only'}
                for alias, spec in self._specs.items()]


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


def _spec(config_text, auth, *, current=False, official=False, fallback=None):
    fallback = fallback or {}
    try:
        config = tomllib.loads(config_text) if isinstance(config_text, str) else {}
    except ValueError:
        config = {}
    profile_name = config.get('model_provider')
    providers = config.get('model_providers')
    provider = providers.get(profile_name, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider, dict):
        provider = {}
    endpoint = provider.get('base_url') or fallback.get('upstreamBaseUrl') or fallback.get('baseUrl')
    if not isinstance(endpoint, str):
        endpoint = None
    model = config.get('model') or fallback.get('testModel') or fallback.get('model')
    model = model if isinstance(model, str) and MODEL_PATTERN.fullmatch(model) else None
    wire = provider.get('wire_api') or fallback.get('protocol') or 'responses'
    wire = 'chat' if wire in ('chat_completions', 'chatCompletions') else wire
    wire = wire if wire in OFFICIAL_ENDPOINTS else 'responses'
    key = None
    if endpoint:
        try:
            parts = urlsplit(endpoint)
            host = (parts.hostname or '').lower().rstrip('.')
            if host in {'api.openai.com', 'api.deepseek.com', 'api.anthropic.com', 'generativelanguage.googleapis.com'} and parts.scheme == 'https':
                kind = 'official_api'
            elif host in ('chatgpt.com', 'chat.openai.com') and parts.scheme == 'https':
                kind = 'official_login'
            elif parts.scheme == 'https' and parts.hostname and not parts.username and not parts.query and not parts.fragment:
                kind = 'relay'
                # Read only the dedicated API-key slots, never a login tokens object.
                indirect = bool(provider.get('env_key'))
                key = None if indirect else provider.get('experimental_bearer_token')
                if not key and not indirect:
                    key = _object(auth).get('OPENAI_API_KEY') or fallback.get('apiKey')
                key = key if isinstance(key, str) and key else None
            else:
                kind = 'unknown'
        except ValueError:
            kind = 'unknown'
    else:
        builtin_api_key = _object(auth).get('OPENAI_API_KEY') if profile_name in (None, 'openai') else None
        kind = 'official_api' if builtin_api_key else 'official_login' if official else 'unknown'
    models = model_choices(([model] if model else []) + model_choices(fallback.get('modelList', [])))
    effort = config.get('model_reasoning_effort')
    effort = effort if effort in REASONING_EFFORTS else None
    return ProviderSpec(kind, model, wire, bool(current), endpoint if kind == 'relay' else None, key, models, effort)


def locate_catalog(source, *, home=None):
    home = checked_path(home if home is not None else Path.home())
    if source == 'cc_switch':
        path = home/'.cc-switch'/'cc-switch.db'
    elif source == 'codexplusplus':
        state = os.environ.get('CODEX_PLUS_STATE_DIR')
        base = checked_path(state) if state else home/'.codex-session-delete'
        path = base/'settings.json'
    else:
        raise ValueError('invalid_source')
    path = checked_path(path)
    if not path.is_file():
        raise ValueError('catalog_not_found')
    return path


def read_catalog(source, source_path, output):
    path, output = checked_path(source_path), checked_path(output)
    if (output == path.parent or path.parent in output.parents or output in path.parents):
        raise ValueError('source_output_overlap')
    if not output.is_dir() or not path.is_file():
        raise ValueError('source_unavailable')
    if source == 'codexplusplus':
        if path.name != 'settings.json' or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('unsupported_source')
        with path.open('rb') as stream:
            body = json.loads(stream.read(2 * 1024 * 1024 + 1))
        profiles = body.get('relayProfiles')
        if not isinstance(profiles, list) or len(profiles) > 1000:
            raise ValueError('unsupported_schema')
        return Catalog([ProviderSpec('official_login', None, 'responses', row.get('id') == body.get('activeRelayId'))
                        if row.get('relayMode') == 'official' and not row.get('officialMixApiKey') else
                        _spec(row.get('configContents', ''), row.get('authContents'),
                              current=row.get('id') == body.get('activeRelayId'),
                              official=row.get('relayMode') == 'official' and not row.get('officialMixApiKey'),
                              fallback=row) for row in profiles if isinstance(row, dict)])
    if source != 'cc_switch' or path.name != 'cc-switch.db' or path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('unsupported_source')
    # SQLite is opened only against a temporary local copy, including WAL/SHM.
    specs = []
    with tempfile.TemporaryDirectory(prefix='provider-copy-', dir=output) as folder:
        destination = Path(folder)/'snapshot.db'
        names = [path, Path(str(path)+'-wal'), Path(str(path)+'-shm')]
        for attempt in range(3):
            before = {}
            for original in names:
                original = checked_path(original)
                if original.exists():
                    info = original.stat()
                    before[original] = (info.st_size, info.st_mtime_ns)
                    if info.st_size > 512 * 1024 * 1024:
                        raise ValueError('source_too_large')
            for original in names:
                copied = Path(str(destination) + str(original)[len(str(path)):])
                if original in before:
                    shutil.copyfile(original, copied)
                elif copied.exists():
                    copied.unlink()
            after = {original: (original.stat().st_size, original.stat().st_mtime_ns)
                     for original in names if original.exists()}
            if before == after:
                break
        else:
            raise ValueError('source_changed_during_copy')
        with closing(sqlite3.connect(destination.as_uri()+'?mode=ro', uri=True)) as connection:
            try:
                connection.execute('PRAGMA query_only=ON')
                if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='providers'").fetchone():
                    raise ValueError('unsupported_schema')
                columns = {row[1] for row in connection.execute('PRAGMA table_info(providers)')}
                if not {'id', 'app_type', 'settings_config'} <= columns:
                    raise ValueError('unsupported_schema')
                extras = [name if name in columns else 'NULL AS '+name for name in ('category', 'meta', 'is_current')]
                query = 'SELECT id,settings_config,' + ','.join(extras) + " FROM providers WHERE app_type='codex' ORDER BY rowid LIMIT 1001"
                rows = connection.execute(query).fetchall()
                if len(rows) > 1000:
                    raise ValueError('too_many_providers')
                for _, settings_text, category, meta_text, current in rows:
                    settings, meta = _object(settings_text), _object(meta_text)
                    binding = meta.get('authBinding') or {}
                    official = category == 'official' or isinstance(binding, dict) and binding.get('authProvider') == 'codex_oauth'
                    specs.append(_spec(settings.get('config', ''), settings.get('auth'), current=current, official=official))
            finally:
                connection.close()
    return Catalog(specs)
