"""Private user settings, separate from anonymous evidence and credential material."""
from dataclasses import asdict
import json
import re
import threading
import uuid

from .models import display_name,model_choices
from .protocol import Protocol,model_name
from .storage import checked_path
from .transport import Target
from .vault import WindowsVault,UnavailableVault,owned_id


SOURCE_ALIAS = re.compile(r'relay-[1-9][0-9]*')


class Profiles:
    def __init__(self,directory,*,vault=None):
        self.directory=checked_path(directory); self.path=checked_path(self.directory/'settings.json')
        self.vault=vault if vault is not None else WindowsVault()
        self.lock=threading.RLock()

    def load(self):
        return self.load_state()[0]

    def has_target(self, target_id):
        return any(row['target_id'] == target_id for row in self.load())

    def load_state(self):
        with self.lock:
            if not self.path.exists(): return [],1
            try:
                if self.path.stat().st_size>2*1024*1024: raise ValueError()
                body=json.loads(self.path.read_bytes())
                if body.get('schema_version')!=1 or not isinstance(body.get('profiles'),list) or len(body['profiles'])>1000: raise ValueError()
                rows=[self.validate({'source_alias':f'relay-{index}'}|row)
                      for index,row in enumerate(body['profiles'],1)]
                for key in ('target_id','source_alias'):
                    if len({row[key] for row in rows})!=len(rows): raise ValueError()
                minimum=max((int(row['source_alias'][6:]) for row in rows),default=0)+1
                next_number=body.get('next_target_number',minimum)
                if type(next_number) is not int or next_number<minimum: raise ValueError()
                return rows,next_number
            except Exception:
                raise ValueError('profiles_unavailable') from None

    @staticmethod
    def validate(row):
        target_id=row['target_id']; owned_id(target_id)
        alias=row.get('source_alias')
        if alias is not None and (not isinstance(alias,str) or not SOURCE_ALIAS.fullmatch(alias)):
            raise ValueError('invalid_profile')
        protocol=Protocol(**row['protocol'])
        reference_wire = row.get('reference_wire_api')
        if reference_wire is not None:
            Protocol(wire_api=reference_wire)
        target=Target(row['base_url'],'validate-configuration',row['model'],protocol)
        interval=row.get('interval_seconds',900)
        import math
        if type(interval) not in (int,float) or not math.isfinite(interval) or interval<=0: raise ValueError('invalid_interval')
        for key,default in (('active_only',True),('credentials_saved',False),('reference_follows_model',True),('reference_saved',False)):
            if type(row.get(key,default)) is not bool: raise ValueError('invalid_profile')
        preset=row.get('reference_preset')
        if preset is not None and (not isinstance(preset,str) or not re.fullmatch(r'[a-z0-9_-]{1,64}',preset)):
            raise ValueError('invalid_profile')
        reference_state=row.get('reference_state')
        if reference_state not in (None,'reference_matched','reference_pending','reference_mismatch','reference_missing'):
            raise ValueError('invalid_profile')
        declared_model=row.get('reference_declared_model')
        reference_protocol=row.get('reference_protocol')
        return {'target_id':target_id,'source_alias':alias,'display_name':display_name(row['display_name']),'base_url':target.base_url,
                'model':target.model,'protocol':asdict(protocol),'reference_model':model_name(row.get('reference_model') or target.model),
                'reference_wire_api':reference_wire,'reference_preset':preset,'reference_saved':row.get('reference_saved',False),
                'reference_state':reference_state,'reference_declared_model':model_name(declared_model) if declared_model is not None else None,
                'reference_protocol':asdict(Protocol(**reference_protocol)) if reference_protocol is not None else None,
                'reference_follows_model':row.get('reference_follows_model',True),'models':model_choices(row.get('models',[])),
                'interval_seconds':interval,'active_only':row.get('active_only',True),'credentials_saved':row.get('credentials_saved',False)}

    def save(self,row):
        value=self.validate(row)
        with self.lock:
            rows,next_number=self.load_state()
            position=next((i for i,row in enumerate(rows) if row['target_id']==value['target_id']),None)
            if position is None:
                if value['source_alias'] not in (None,f'relay-{next_number}'):
                    raise ValueError('profiles_unavailable')
                value['source_alias']=f'relay-{next_number}'
                next_number+=1
                rows.append(value)
            else:
                previous=rows[position]
                if value['source_alias'] not in (None,previous['source_alias']):
                    raise ValueError('profiles_unavailable')
                value['source_alias']=previous['source_alias']
                rows[position]=value
            self._write_state(rows,next_number)

    def _write_state(self,rows,next_number):
        self.directory.mkdir(parents=True,exist_ok=True)
        path=checked_path(self.directory/('settings-'+uuid.uuid4().hex+'.tmp'))
        try:
            with path.open('x',encoding='utf-8') as stream:
                json.dump({'schema_version':1,'profiles':rows,'next_target_number':next_number},stream,
                          ensure_ascii=False,allow_nan=False,indent=2)
            checked_path(self.path); path.replace(self.path)
        finally:
            if path.exists(): path.unlink()

    def remove(self,target_id,*,credentials_saved=False):
        with self.lock:
            rows,next_number=self.load_state()
            row=next((row for row in rows if row['target_id']==target_id),None)
            if row is None:
                raise ValueError('profiles_unavailable')
            previous=None
            if self.vault.available:
                try:
                    previous=self.vault.read(target_id)
                    if previous is not None:
                        self.vault.delete(target_id)
                except Exception:
                    raise ValueError('vault_unavailable') from None
            elif credentials_saved or row['credentials_saved'] or row['reference_saved']:
                raise ValueError('vault_unavailable')
            try:
                self._write_state([candidate for candidate in rows if candidate['target_id']!=target_id],next_number)
            except Exception:
                if previous:
                    try:
                        self.vault.write(target_id,previous)
                    except Exception:
                        raise ValueError('target_delete_rollback_failed') from None
                raise ValueError('profiles_unavailable') from None

    def save_secret(self,target_id,secrets):
        self.vault.write(target_id,secrets)

    def secret(self,row):
        return self.vault.read(row['target_id']) if row['credentials_saved'] or row.get('reference_saved') else None
