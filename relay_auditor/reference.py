"""Numeric reference packs with exact matching and untrusted-import provenance."""
from dataclasses import dataclass
from datetime import datetime,timezone
import json
import math
import re
from .storage import checked_path
from .protocol import model_name

@dataclass(frozen=True)
class ReferencePack:
    model:str
    reference_model:str
    protocol_id:str
    completed_at:str
    features:tuple
    suite_version:str='fingerprint-v1'

    @classmethod
    def load(cls,path):
        path=checked_path(path)
        if path.stat().st_size>2*1024*1024: raise ValueError('reference_pack_too_large')
        try:
            body=json.loads(path.read_bytes())
            if set(body)!={'schema_version','model','reference_model','protocol_id','completed_at','baseline_features','suite_version'} or body['schema_version']!=1: raise ValueError()
            if body['suite_version']!='fingerprint-v1' or not re.fullmatch('synthetic-v1-[a-f0-9]{16}',body['protocol_id']): raise ValueError()
            model_name(body['model']); model_name(body['reference_model'])
            if datetime.fromisoformat(body['completed_at']).tzinfo is None: raise ValueError()
            rows=body['baseline_features']
            if not isinstance(rows,list) or not 12<=len(rows)<=200 or any(not isinstance(row,list) or len(row)!=429 or any(type(n) not in (int,float) or not math.isfinite(n) or n<0 for n in row) for row in rows): raise ValueError()
            return cls(body['model'],body['reference_model'],body['protocol_id'],body['completed_at'],tuple(tuple(row) for row in rows))
        except (ValueError,TypeError,KeyError): raise ValueError('invalid_reference_pack') from None

    def matches(self,target,reference_model):
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(self.completed_at)).total_seconds()
        return self.model==target.model and self.reference_model==reference_model and self.protocol_id==target.protocol.identity and 0<=age<=7*86400

    def install(self,store,target,reference_model):
        if not self.matches(target,reference_model): raise ValueError('reference_not_comparable')
        return store.put_baseline(self.model,self.protocol_id,[list(row) for row in self.features],self.completed_at,self.reference_model,provenance_level='user_history')
