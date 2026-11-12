"""Explicit study actions, no auto collection or credential discovery."""
import json
import re
import uuid
from .calibration import freeze,read_study,collect_trial,evaluate
from .official import restore_reference
from .protocol import Protocol
from .storage import checked_path
from .prompts import hidden

def command(args,store):
    protocol=Protocol(wire_api=args.wire_api,stream=args.stream,reasoning_effort=args.reasoning_effort)
    if args.command=='calibration-init':
        manifest=freeze(args.primary_model,args.alternative_model,protocol,samples=args.samples,trials=args.trials,
                        seed=args.seed,scope=args.study_scope,
                        audit_index=args.calibration_audit_index,suite=args.suite,family=args.family)
        study_id=manifest['manifest_hash'][:32]; root=checked_path(store.directory/'studies'/study_id)
        root.mkdir(parents=True,exist_ok=True)
        with checked_path(root/'manifest.json').open('x',encoding='utf-8') as output: json.dump(manifest,output,indent=2)
        return {'study_id':study_id,'manifest':manifest}
    if not args.study_id or not re.fullmatch('[a-f0-9]{32}',args.study_id): raise ValueError('invalid_study_id')
    root=checked_path(store.directory/'studies'/args.study_id)
    if args.command=='calibration-report':
        manifest,records=read_study(root); return evaluate(manifest,records)
    if args.request_limit is None or args.token_limit is None: raise ValueError('explicit_calibration_budget_required')
    lock=checked_path(root/'collect.lock'); lock.open('x').close()
    try:
        manifest,records=read_study(root); protocol=Protocol(**manifest['protocol'])
        if args.scenario not in manifest['scenarios']:
            raise ValueError('invalid_trial')
        store.set_limits(args.request_limit,args.token_limit)
        key=hidden('独立官方校准 API Key（仅固定官方接口，隐藏输入）：')
        primary=restore_reference(manifest['official_preset'],key,manifest['primary_model'],protocol)
        alternative=restore_reference(manifest['official_preset'],key,manifest['alternative_model'],protocol)
        outcome=collect_trial(manifest,args.scenario,args.trial,args.phase,primary,alternative,store,records=records)
        temporary=checked_path(root/('outcomes-'+uuid.uuid4().hex+'.tmp'))
        try:
            with temporary.open('x',encoding='utf-8') as output: json.dump(records+[outcome],output)
            checked_path(root/'outcomes.json'); temporary.replace(root/'outcomes.json')
        finally:
            if temporary.exists(): temporary.unlink()
        return outcome
    finally: lock.unlink()
