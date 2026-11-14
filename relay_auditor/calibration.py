"""Frozen controlled studies. No credential discovery; collecting is explicit/paid.

Only synthetic prompts and fixed official API targets are accepted. Outcomes are
parsed grades/counts, never raw requests/responses. Passing statistics proposes a
review candidate, never promotes the product's calibrated-model registry.
"""
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import secrets

from . import assessment,exam
from .exam_registry import get_exam_spec,is_exam_suite
from .calibration_metrics import (TRIAL_ERROR_CODES, extract_exam_score_counts,
                                  checked_exam_score_counts, make_trial_failure,
                                  checked_trial_failure, quality_metrics)
from .controller import Cancelled,Service
from .families import PROFILES,family_for
from .official import PRESETS,compatible_protocols,official_model,restore_reference
from .model_capabilities import supports_parameters
from .protocol import Protocol,model_name
from .suites import SUITES,cases
from .statistics import MINIMUM_PAIRED_SAMPLES,compare_paired,paired_p_value,spending_alpha
from .transport import APIClient,EndpointError
from .storage import checked_path
from .storage import BudgetExceeded

PRIMARY_SCENARIOS=('healthy','substitution')
SCENARIOS=PRIMARY_SCENARIOS+('reasoning_changed','context_truncated','mixed_10','mixed_30','mixed_50')
SCOPES={'primary': PRIMARY_SCENARIOS, 'extended': SCENARIOS}
TASK_COUNTS=('attempted','valid','correct','valid_pairs','reference_correct','target_correct')


def _digest(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _trial_seed(manifest,scenario,index,phase):
    return manifest['seed']+(10**9 if phase=='validation' else 0)+SCENARIOS.index(scenario)*10**7+index*1000


def freeze(primary_model,alternative_model,protocol,*,samples=None,trials=100,seed=None,
           frozen_at=None,scope='primary',audit_index=1,suite=None,family=None):
    if (suite not in (None,'assessment-v4') and not is_exam_suite(suite)
            or family not in (None,'gpt','deepseek','claude','gemini')):
        raise ValueError('invalid_study')
    family=family or 'gpt'
    is_exam=is_exam_suite(suite)
    try:
        spec=get_exam_spec(family,suite) if is_exam else None
    except ValueError:
        raise ValueError('invalid_study') from None
    # Native assessments retain their initial default-only settings. Native exams
    # use the exact shared model policy checked by compatible_protocols below.
    if family in ('claude','gemini') and (not (suite=='assessment-v4' or is_exam) or scope!='primary'
            or not is_exam
            and (protocol.reasoning_effort is not None or protocol.temperature is not None)):
        raise ValueError('invalid_study')
    samples=(spec.sizes[0] if is_exam else 40) if samples is None else samples
    if is_exam and samples not in spec.sizes: raise ValueError('invalid_study')
    model_name(primary_model); model_name(alternative_model)
    if primary_model==alternative_model or type(samples) is not int or not 1<=samples<=200 or type(trials) is not int or not 100<=trials<=1000:
        raise ValueError('invalid_study')
    if seed is None: seed=secrets.randbelow(10**9)
    if type(seed) is not int or not 0<=seed<10**9: raise ValueError('invalid_study')
    if not isinstance(scope,str) or scope not in SCOPES or type(audit_index) is not int or not 1<=audit_index<=100000:
        raise ValueError('invalid_study')
    preset={'gpt':'openai','deepseek':'deepseek','claude':'anthropic','gemini':'google'}[family]
    if protocol.wire_api not in PRESETS[preset].wires or any(
        family_for(model)!=family or official_model(preset,model)!=model
        or not compatible_protocols(preset,protocol,protocol,model)
        for model in (primary_model,alternative_model)
    ):
        raise ValueError('invalid_study_model')
    frozen_at=frozen_at or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(frozen_at).tzinfo is None: raise ValueError('invalid_study')
    scenarios=SCOPES[scope]
    changed_effort='none' if protocol.reasoning_effort=='low' else 'low'
    if ('reasoning_changed' in scenarios and (
            family=='deepseek' and protocol.reasoning_effort=='minimal' and changed_effort=='low'
            or not supports_parameters(primary_model,replace(protocol,reasoning_effort=changed_effort)))):
        raise ValueError('unsupported_study_reasoning')
    try:
        hashes={name:hashlib.sha256(Path(__file__).with_name(name+'.py').read_bytes()).hexdigest()
                for name in ('assessment','planning','families','controller','suites','protocol','statistics',
                             'calibration','storage','transport','official','adapters','exam','grading')}
        for name in ('exam_generators','exam_registry','native_exam_generators','model_capabilities','calibration_metrics'):
            source=Path(__file__).with_name(name+'.py')
            if source.exists(): hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError: raise ValueError('calibration_source_required') from None
    cuts=[(index*trials+2)//3 for index in range(4)]
    validation_blocks=[{'start_trial': start, 'stop_trial': stop} for start,stop in zip(cuts,cuts[1:])]
    retries=spec.retry_requests_per_side(samples)*2 if is_exam else samples*4 if suite is not None else 0
    primary_requests=len(scenarios)*(trials+10)*samples*2
    retry_requests=(len(scenarios)-(1 if 'context_truncated' in scenarios else 0))*(trials+10)*retries
    body={'schema_version':2,'frozen_at':frozen_at,'implementation_hashes':hashes,
          'suite_version':spec.version if is_exam else assessment.VERSION,'suite_selection':suite,
          'family':family,'official_preset':preset,'official_base_url':PRESETS[preset].base_url,
          'specialist_context_suite':SUITES['context']['version'] if 'context_truncated' in scenarios else None,
          'primary_model':primary_model,'alternative_model':alternative_model,
          'protocol':asdict(protocol),'samples':samples,'trials':trials,'pilot_trials':10,'seed':seed,
          'scope':scope,'audit_index':audit_index,'alpha':spending_alpha(audit_index),
          'validation_date_basis':'UTC','validation_blocks':validation_blocks,
          'minimum_effect':.10,'minimum_pairs':MINIMUM_PAIRED_SAMPLES,'scenarios':list(scenarios),
          'changed_reasoning_effort':changed_effort,
          'planned_requests':primary_requests,'planned_retry_requests':retry_requests,
          'max_requests':primary_requests+retry_requests,
          'retry_policy':{'enabled':bool(retries),'max_retries_per_item':spec.max_retries_per_item if is_exam else len(assessment.RETRY_DELAYS) if retries else 0,
                          'delays_seconds':list(assessment.RETRY_DELAYS) if retries else [],
                          'retryable_errors':sorted(exam.RETRYABLE if is_exam else assessment.RETRYABLE) if retries else [],
                          'max_retry_requests_per_trial':retries,'context_control_retries':0},
          'interval_method':'clopper_pearson_two_sided_95','context_control_scope':'separate_specialist_control',
          'false_positive_upper':.05,'power_lower':.80}
    return body|{'manifest_hash':_digest(body)}


def validate(manifest):
    try:
        expected=freeze(manifest['primary_model'],manifest['alternative_model'],Protocol(**manifest['protocol']),
                        samples=manifest['samples'],trials=manifest['trials'],seed=manifest['seed'],frozen_at=manifest['frozen_at'],
                        scope=manifest['scope'],audit_index=manifest['audit_index'],
                        suite=manifest['suite_selection'],family=manifest['family'])
        if manifest!=expected: raise ValueError()
    except Exception: raise ValueError('invalid_or_modified_study') from None


def _validation_timeline(manifest, records):
    timeline=[]
    for block in manifest['validation_blocks']:
        start,stop=block['start_trial'],block['stop_trial']
        days=[row['day'] for row in records if row['phase']=='validation' and start<=row['trial_index']<stop]
        timeline.append({**block,'sample_count':len(days), 'planned_sample_count':(stop-start)*len(manifest['scenarios']),
                         'first_day':min(days,default=None),'last_day':max(days,default=None)})
    return timeline


def _cdf(k,n,p):
    if k<0: return 0.0
    if k>=n: return 1.0
    if p<=0: return 1.0
    if p>=1: return 0.0
    values=[math.lgamma(n+1)-math.lgamma(i+1)-math.lgamma(n-i+1)+i*math.log(p)+(n-i)*math.log1p(-p) for i in range(k+1)]
    peak=max(values)
    return min(1,math.exp(peak)*sum(math.exp(x-peak) for x in values))


def binomial_interval(successes,n):
    if not n: return [0.0,1.0]
    def solve(k,q):
        left,right=0.0,1.0
        for _ in range(65):
            mid=(left+right)/2
            if _cdf(k,n,mid)>q: left=mid
            else: right=mid
        return (left+right)/2
    return [0.0 if successes==0 else solve(successes-1,.975),1.0 if successes==n else solve(successes,.025)]


class _TrialBudget:
    """Share persisted spend with production, keeping trial decisions and counts separate."""
    def __init__(self,store,manifest):
        self.store=store
        self.audit_index=manifest['audit_index']
        self.alpha=manifest['alpha']
        self.requests=self.estimated_tokens=self.unknown_usage=self.reported_tokens=0

    def next_audit(self):
        return self.audit_index,self.alpha

    def reserve_batch(self,requests,per_call):
        return self.store.reserve_batch(requests,per_call)

    def release_batch(self,batch):
        self.store.release_batch(batch)

    def available(self,requests,tokens):
        return self.store.available(requests,tokens)

    def reserve(self,estimate,role,*,batch=None):
        # Both sides are actually paid calls to official APIs.
        ticket=self.store.reserve(estimate,'reference',batch=batch)
        self.requests+=1
        self.estimated_tokens+=estimate
        self.unknown_usage+=1
        return ticket

    def settle(self,ticket,usage):
        self.store.settle(ticket,usage)
        total=(usage or {}).get('total_tokens')
        if type(total) is int and total>=0:
            self.reported_tokens+=total
            self.unknown_usage-=1


def _context_control(service,monitor,samples,seed,result):
    """Independent context-v1 specialist control, outside the one-click claim."""
    rows=list(cases('context',samples,seed=seed))
    per_call=max(len(row.prompt.encode()) for row in rows)+monitor.target.protocol.max_output_tokens+256
    batch=service.store.reserve_batch(len(rows)*2,per_call)
    pairs=[]
    result.update(response_count=0,network_failures=0)
    try:
        for index,case in enumerate(rows):
            values={}
            for reference in ((True,False) if index%2 else (False,True)):
                if reference and monitor.reference_error:
                    continue
                try:
                    completion=service._call(monitor,case,reference=reference,batch=batch)
                except EndpointError:
                    result['network_failures']+=1
                    continue
                result['response_count']+=1
                grade=case.grade(completion.text) if completion.complete else None
                if grade and grade['valid']:
                    values[reference]=grade['correct']
            pairs.append((values.get(True),values.get(False)))
    finally:
        result['paired_result']=compare_paired(pairs,alpha=service.store.next_audit()[1])
        if result['paired_result']['valid_pairs'] == samples and samples >= MINIMUM_PAIRED_SAMPLES:
            result['audit_index']=service.store.audit_index
        service.store.release_batch(batch)


def collect_trial(manifest,scenario,index,phase,primary,alternative,store,*,records=(),client_factory=APIClient,date=None):
    validate(manifest)
    checked_records(manifest,list(records))
    day=datetime.now(timezone.utc).date().isoformat() if date is None else date
    if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        raise ValueError('invalid_trial_date')
    try: datetime.strptime(day,'%Y-%m-%d')
    except (ValueError,TypeError): raise ValueError('invalid_trial_date') from None
    if scenario not in manifest['scenarios'] or phase not in ('pilot','validation') or type(index) is not int or not 0<=index<(manifest['pilot_trials'] if phase=='pilot' else manifest['trials']):
        raise ValueError('invalid_trial')
    same=[row for row in records if row.get('manifest_hash')==manifest['manifest_hash']]
    if any(row.get('phase')==phase and row.get('scenario')==scenario and row.get('trial_index')==index for row in same):
        raise ValueError('trial_already_collected')
    pilots=[r for r in same if r['phase']=='pilot']
    if phase=='validation' and (len(pilots)!=len(manifest['scenarios'])*manifest['pilot_trials']
                                or any(r['day']>=day for r in pilots)):
        raise ValueError('independent_pilot_date_required')
    if phase=='validation':
        timeline=_validation_timeline(manifest,same)
        position=next(i for i,block in enumerate(timeline) if block['start_trial']<=index<block['stop_trial'])
        if any(block['sample_count']!=block['planned_sample_count'] or block['last_day']>=day
               for block in timeline[:position]):
            raise ValueError('validation_block_not_ready')
        if any(block['sample_count'] for block in timeline[position+1:]):
            raise ValueError('validation_block_not_ready')
    protocol=Protocol(**manifest['protocol'])
    preset=manifest['official_preset']
    if (primary.role!='reference' or alternative.role!='reference' or primary.base_url.rstrip('/')!=manifest['official_base_url']
        or alternative.base_url.rstrip('/')!=primary.base_url.rstrip('/') or primary.model!=manifest['primary_model']
        or alternative.model!=manifest['alternative_model'] or primary.protocol!=protocol or alternative.protocol!=protocol
        or primary.official_preset not in (None,preset) or alternative.official_preset not in (None,preset)):
        raise ValueError('study_targets_mismatch')
    primary=restore_reference(preset,primary.api_key,primary.model,protocol)
    alternative=restore_reference(preset,alternative.api_key,alternative.model,protocol)
    seed=_trial_seed(manifest,scenario,index,phase)
    rng=random.Random(seed)
    changed=replace(primary,protocol=replace(protocol,reasoning_effort=manifest['changed_reasoning_effort']))
    mixture=int(scenario.split('_')[1])/100 if scenario.startswith('mixed_') else 0
    alternative_calls=0
    mixture_routes={}

    class ControlledClient:
        def __init__(self,target):
            self.reference=target.role=='reference'

        def complete(self,case):
            nonlocal alternative_calls
            selected=primary
            if not self.reference:
                if mixture and case.item_id not in mixture_routes:
                    mixture_routes[case.item_id]=rng.random()<mixture
                if scenario=='substitution' or mixture_routes.get(case.item_id,False):
                    selected=alternative
                    alternative_calls+=1
                elif scenario=='reasoning_changed':
                    selected=changed
                elif scenario=='context_truncated':
                    case=replace(case,prompt=case.prompt[:len(case.prompt)//4]+'\nReturn the final answer as JSON.')
            return client_factory(selected).complete(case)

    budget=_TrialBudget(store,manifest)
    service=Service(budget,client_factory=ControlledClient)
    alias=service.configure('https://calibration.invalid/v1','study-placeholder',primary.model,protocol)
    monitor=service.monitors[alias]
    monitor.reference=primary
    monitor.reference_preset=primary.official_preset
    monitor.reference_declared_model=primary.model
    result={}
    cancelled=False
    stop_reason=None
    failure=None
    try:
        if scenario=='context_truncated':
            _context_control(service,monitor,manifest['samples'],seed,result)
        elif is_exam_suite(manifest['suite_selection']):
            from .planning import exam_plan
            plan=exam_plan(monitor,manifest['samples'],'paired',store.budget(),suite_version=manifest['suite_version'])
            exam.run_exam(service,monitor,plan,result,seed=seed)
        else:
            options={'recover':True} if manifest['retry_policy']['enabled'] else {}
            assessment.run_assessment(service,monitor,manifest['samples'],result,seed=seed,**options)
    except (KeyboardInterrupt,Cancelled):
        cancelled=True
        failure=make_trial_failure('cancelled',result,manifest['samples'])
    except BudgetExceeded:
        stop_reason='budget_exhausted'
        failure=make_trial_failure('budget_exhausted',result,manifest['samples'])
    except EndpointError as error:
        # A failed trial remains in the denominator. The production runner owns
        # its stop/retry rule; the study never retries a discarded whole paper.
        failure=make_trial_failure(str(error),result,manifest['samples'])
    if is_exam_suite(manifest['suite_selection']) and scenario!='context_truncated' and 'paired_result' not in result:
        attempted={}
        for item in result.get('item_results',[]):
            if item['attempts']:
                answer=_exam_item_score(item)
                attempted.setdefault(item['question_number'],{})[item['source_kind']]=answer
        pairs=[(sides.get('reference'),sides.get('relay')) for _,sides in sorted(attempted.items())]
        result['paired_result']=assessment.assessment_comparison(pairs,manifest['samples'],alpha=None)
    comparison=result.get('paired_result') or compare_paired([],alpha=manifest['alpha'])
    suite=manifest['specialist_context_suite'] if scenario=='context_truncated' else manifest['suite_version']
    outcome={'schema_version':2,'manifest_hash':manifest['manifest_hash'],'suite_version':suite,'day':day,'phase':phase,
            'scenario':scenario,'trial_index':index,'audit_index':manifest['audit_index'],
            'applied_audit_index':result.get('audit_index'),
            'valid_pairs':comparison['valid_pairs'],'attempted_pairs':comparison['attempted_pairs'],
            'regressions':comparison['regressions'],'improvements':comparison['improvements'],'p_value':comparison['p_value'],
            'complete':not cancelled and comparison['valid_pairs']==manifest['samples'] and comparison['valid_pairs']>=manifest['minimum_pairs'],
            'detected':not cancelled and comparison['status']=='degraded','network_failures':result.get('network_failures',0),
            'response_count':result.get('response_count',0),
            'retry_requests':result.get('retry_requests',0),
            'alternative_calls':alternative_calls,'validation_state':'experimental','cancelled':cancelled,
            'requests':budget.requests,'reported_tokens':budget.reported_tokens,
            'unknown_usage':budget.unknown_usage,'estimated_tokens':budget.estimated_tokens,'estimated_cost':None}
    if stop_reason is not None: outcome['stop_reason']=stop_reason
    if failure is not None: outcome['trial_failure']=failure
    if is_exam_suite(manifest['suite_selection']) and scenario!='context_truncated':
        outcome['exam_score_counts']=extract_exam_score_counts(result,manifest['samples'])
    if phase=='pilot' and scenario!='context_truncated':
        outcome['pilot_tasks']=result.get('assessment_tasks',[])
        # Custom transports can throw arbitrary exception text. Only fixed
        # service codes, never that text, enter anonymous per-item evidence.
        allowed_codes=TRIAL_ERROR_CODES | {None,'answer_format','recovered_format'}
        outcome['pilot_items']=[{**item,'error_code':item['error_code'] if item['error_code'] in allowed_codes else 'remote_error'}
                                for item in result.get('item_results',[])]
    return outcome


def _exam_item_score(item):
    """Separate an observed format loss from a slot's ungraded default state."""
    from .grading import GRADING_ISSUES
    if type(item['correct']) is bool:
        if (item['attempts']>0 and item['grading_issue'] is None and
            (item['format_state'],item['error_code']) in (('valid',None),('recovered_format','recovered_format'))):
            return item['correct']
    elif item['correct'] is None:
        if (item['attempts']>0 and item['format_state']==item['error_code']=='answer_format'
            and item['grading_issue'] in GRADING_ISSUES):
            return False
        if (item['grading_issue'] is None and item['format_state']=='answer_format'
            and item['error_code'] not in ('answer_format','recovered_format')):
            return None
    raise ValueError('invalid_outcomes')


def _checked_exam_pilot_items(manifest,row):
    """Match every anonymous pilot slot to its frozen paper, then reconcile counts."""
    if 'pilot_items' not in row:
        return None
    items=row['pilot_items']
    if items==[]:
        if any(row.get(field,0) for field in ('requests','retry_requests','attempted_pairs','valid_pairs','regressions','improvements')):
            raise ValueError('invalid_outcomes')
        return None
    if not isinstance(items,list) or len(items)!=2*manifest['samples']:
        raise ValueError('invalid_outcomes')
    cases=tuple(exam.exam_cases(manifest['family'],manifest['samples'],
                               _trial_seed(manifest,row['scenario'],row['trial_index'],row['phase']),
                               suite_version=manifest['suite_version']))
    slots={(item['question_number'],item['source_kind']):item for item in items}
    if len(slots)!=len(items): raise ValueError('invalid_outcomes')
    pairs=[]
    ordered=[]
    for question,(case,difficulty) in enumerate(cases,1):
        sides={}
        attempted=False
        for source in ('reference','relay'):
            item=slots.get((question,source))
            if item is None or any(item[field]!=value for field,value in (
                    ('question_number',question),('seed',case.seed),('task_kind',case.kind),
                    ('template',case.variant),('difficulty',difficulty))):
                raise ValueError('invalid_outcomes')
            sides[source]=_exam_item_score(item)
            attempted=attempted or item['attempts']>0
            ordered.append(item)
        if attempted: pairs.append((sides['reference'],sides['relay']))
    requests=sum(item['attempts'] for item in ordered)
    retries=sum(max(item['attempts']-1,0) for item in ordered)
    spec=get_exam_spec(manifest['family'],manifest['suite_version'])
    if (row['requests']!=requests or row.get('retry_requests',0)!=retries or any(
            sum(max(item['attempts']-1,0) for item in ordered if item['source_kind']==source)>spec.retry_requests_per_side(manifest['samples'])
            for source in ('reference','relay'))):
        raise ValueError('invalid_outcomes')
    comparison=compare_paired(pairs,alpha=manifest['alpha'])
    if any(row[field]!=comparison[field] for field in ('attempted_pairs','valid_pairs','regressions','improvements','p_value')):
        raise ValueError('invalid_outcomes')
    return tuple(ordered)


def _pilot_task_totals(pilot_rows):
    by_task={}
    for trial in pilot_rows:
        for row in trial.get('pilot_tasks',[]):
            key=(row['task_kind'],row['difficulty'])
            total=by_task.setdefault(key,{'task_kind':key[0],'difficulty':key[1],**dict.fromkeys(TASK_COUNTS,0)})
            for field in TASK_COUNTS:
                total[field]+=row.get(field,0)
    return list(by_task.values())


def _pilot_template_totals(pilot_rows):
    by_template={}
    for trial in pilot_rows:
        for item in trial.get('pilot_items',[]):
            key=(item['source_kind'],item['task_kind'],item['template'],item['difficulty'])
            total=by_template.setdefault(key,dict(source_kind=key[0],task_kind=key[1],template=key[2],difficulty=key[3],
                                                  sample_count=0,attempted=0,attempts=0,scorable=0,correct=0,
                                                  format_failures=0,format_recovered=0,uncompleted=0))
            total['sample_count']+=1
            total['attempted']+=int(item['attempts']>0)
            total['attempts']+=item['attempts']
            total['scorable']+=int(type(item['correct']) is bool)
            total['correct']+=int(item['correct'] is True)
            total['format_failures']+=int(item['error_code']=='answer_format')
            total['format_recovered']+=int(item['format_state']=='recovered_format')
            total['uncompleted']+=int(item['correct'] is None and item['error_code']!='answer_format')
    return list(by_template.values())


def _pilot_template_diagnostics(manifest,pilot_rows):
    """Describe checked same-question observations, without grading a pilot paper."""
    result={'schema_version':1,'evidence':'descriptive_pilot','evidence_state':'not_applicable',
            'pilot_trials':len(pilot_rows),'item_evidence_trials':0,'missing_item_evidence_trials':0,
            'completed_trials':sum(row['complete'] for row in pilot_rows),
            'cancelled_trials':sum(row['cancelled'] for row in pilot_rows),'templates':[]}
    if not is_exam_suite(manifest['suite_selection']) or any(row['scenario']=='context_truncated' for row in pilot_rows):
        return result
    by_template={}
    for row in pilot_rows:
        items=row.get('pilot_items',[])
        if not items:
            result['missing_item_evidence_trials']+=1
            continue
        result['item_evidence_trials']+=1
        questions={}
        for item in items:
            questions.setdefault(item['question_number'],{})[item['source_kind']]=item
        for sides in questions.values():
            reference=sides['reference']
            key=(reference['task_kind'],reference['template'],reference['difficulty'])
            if key not in by_template:
                by_template[key]={'task_kind':key[0],'template':key[1],'difficulty':key[2],
                    **dict.fromkeys(('planned_pairs','attempted_pairs','valid_pairs','unknown_pairs',
                                     'both_correct','both_incorrect','regressions','improvements'),0),
                    'observed_score_gap':None,
                    **{source:dict.fromkeys(('attempted','requests','retry_requests','scored','correct',
                                             'format_losses','format_recovered','unknown'),0)
                       for source in ('reference','relay')}}
            total=by_template[key]
            total['planned_pairs']+=1
            total['attempted_pairs']+=int(any(item['attempts']>0 for item in sides.values()))
            scores={}
            for source,item in sides.items():
                score=_exam_item_score(item)
                scores[source]=score
                counts=total[source]
                counts['attempted']+=int(item['attempts']>0)
                counts['requests']+=item['attempts']
                counts['retry_requests']+=max(item['attempts']-1,0)
                counts['scored']+=int(score is not None)
                counts['correct']+=int(score is True)
                counts['format_losses']+=int(item['error_code']=='answer_format')
                counts['format_recovered']+=int(item['format_state']=='recovered_format')
                counts['unknown']+=int(score is None)
            ref,relay=scores['reference'],scores['relay']
            if ref is None or relay is None:
                total['unknown_pairs']+=1
            else:
                total['valid_pairs']+=1
                category=('both_correct' if ref and relay else 'both_incorrect' if not ref and not relay
                          else 'regressions' if ref else 'improvements')
                total[category]+=1
    for key,total in sorted(by_template.items()):
        valid=total['valid_pairs']
        total['observed_score_gap']=(total['regressions']-total['improvements'])/valid if valid else None
        for source in ('reference','relay'):
            counts=total[source]
            counts['score_rate']=counts['correct']/counts['scored'] if counts['scored'] else None
        result['templates'].append(total)
    result['evidence_state']=('unavailable' if not result['item_evidence_trials'] else
                              'partial' if result['missing_item_evidence_trials'] else 'available')
    return result


def evaluate(manifest,records):
    validate(manifest); result={}
    checked_records(manifest,records)
    for kind in manifest['scenarios']:
        rows=[r for r in records if r.get('phase')=='validation' and r.get('scenario')==kind]
        pilots=[r for r in records if r['phase']=='pilot' and r['scenario']==kind]
        n=len(rows); positives=sum(r.get('detected') is True and r.get('complete') is True for r in rows)
        unknown=sum(r.get('complete') is not True for r in rows)
        # Unresolved healthy trials count against false-positive acceptance.
        interval=binomial_interval(positives+unknown if kind=='healthy' else positives,n)
        diagnostics=_pilot_template_diagnostics(manifest,pilots)
        if kind=='context_truncated': diagnostics['evidence_state']='not_applicable'
        result[kind]={'sample_count':n,'detected':positives,'unknown':unknown,'interval':interval,
                      'observed_interval':binomial_interval(positives,n),
                      'pilot_trials':len(pilots),'pilot_tasks':_pilot_task_totals(pilots),
                      'pilot_templates':_pilot_template_totals(pilots),
                      'pilot_diagnostics':diagnostics,
                      'quality_metrics':quality_metrics(manifest,pilots+rows),
                      'pilot_usage':{key:sum(r[key] for r in pilots)
                                     for key in ('requests','reported_tokens','unknown_usage','estimated_tokens')},
                      'requests':sum(r.get('requests',0) for r in rows),'reported_tokens':sum(r.get('reported_tokens',0) for r in rows),
                      'unknown_usage':sum(r.get('unknown_usage',0) for r in rows),'estimated_cost':None}
    pilot_days=[row['day'] for row in records if row['phase']=='pilot']
    timeline=_validation_timeline(manifest,records)
    enough=(len(pilot_days)==len(manifest['scenarios'])*manifest['pilot_trials']
            and all(block['sample_count']==block['planned_sample_count'] for block in timeline)
            and max(pilot_days)<timeline[0]['first_day']
            and all(before['last_day']<after['first_day'] for before,after in zip(timeline,timeline[1:])))
    passed=enough and result['healthy']['interval'][1]<=manifest['false_positive_upper'] and result['substitution']['interval'][0]>=manifest['power_lower']
    return {'schema_version':2,'manifest_hash':manifest['manifest_hash'],'validation_state':'experimental',
            'scope':manifest['scope'],'suite_version':manifest['suite_version'],'audit_index':manifest['audit_index'],
            'alpha':manifest['alpha'],'planned_requests':manifest['planned_requests'],
            'planned_retry_requests':manifest['planned_retry_requests'],'max_requests':manifest['max_requests'],
            'family':manifest['family'],'official_preset':manifest['official_preset'],
            'interval_method':manifest['interval_method'],'context_control_scope':manifest['context_control_scope'],
            'validation_blocks':timeline,'validation_date_basis':manifest['validation_date_basis'],
            'specialist_context_suite':manifest['specialist_context_suite'],
            'candidate_pass':passed,'requires_project_review':True,'scenarios':result}


def checked_records(manifest,records):
    spec=get_exam_spec(manifest['family'],manifest['suite_version']) if is_exam_suite(manifest['suite_selection']) else None
    allowed_tasks=spec.task_kinds if spec else PROFILES[manifest['family']].tasks
    if not isinstance(records,list) or len(records)>len(manifest['scenarios'])*(manifest['trials']+manifest['pilot_trials']): raise ValueError('invalid_outcomes')
    seen=set()
    for row in records:
        if not isinstance(row,dict) or row.get('schema_version')!=2 or row.get('manifest_hash')!=manifest['manifest_hash']:
            raise ValueError('invalid_outcomes')
        key=(row.get('phase'),row.get('scenario'),row.get('trial_index'))
        suite=manifest['specialist_context_suite'] if key[1]=='context_truncated' else manifest['suite_version']
        if (row.get('audit_index')!=manifest['audit_index'] or row.get('suite_version')!=suite
            or key[0] not in ('pilot','validation') or key[1] not in manifest['scenarios'] or type(key[2]) is not int or
            not 0<=key[2]<(manifest['pilot_trials'] if key[0]=='pilot' else manifest['trials']) or
            any(type(row.get(field)) is not bool for field in ('complete','detected','cancelled')) or
            not isinstance(row.get('day'),str) or not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}',row['day'])): raise ValueError('invalid_outcomes')
        if 'stop_reason' in row and (type(row['stop_reason']) is not str or row['stop_reason']!='budget_exhausted'
                or row['complete'] or row['cancelled'] or row['detected']):
            raise ValueError('invalid_outcomes')
        try: datetime.strptime(row['day'],'%Y-%m-%d')
        except ValueError: raise ValueError('invalid_outcomes') from None
        if key in seen: raise ValueError('duplicate_outcome')
        seen.add(key)
        for field in ('valid_pairs','attempted_pairs','regressions','improvements','requests','response_count','network_failures','alternative_calls','reported_tokens','unknown_usage','estimated_tokens'):
            if type(row.get(field)) is not int or not 0<=row[field]<=10**10: raise ValueError('invalid_outcomes')
        retry_limit=0 if row['scenario']=='context_truncated' else manifest['retry_policy']['max_retry_requests_per_trial']
        retries=row.get('retry_requests',0)
        if type(retries) is not int or not 0<=retries<=retry_limit: raise ValueError('invalid_outcomes')
        if (row['valid_pairs']>row['attempted_pairs'] or row['attempted_pairs']>manifest['samples'] or
            row['regressions']+row['improvements']>row['valid_pairs'] or row['requests']>manifest['samples']*2+retry_limit or
            row['requests']-retries>manifest['samples']*2 or retries>row['requests'] or
            row['response_count']>row['requests'] or row['complete'] and (row['valid_pairs']<manifest['minimum_pairs'] or row['valid_pairs']!=manifest['samples'])):
            raise ValueError('invalid_outcomes')
        valid=row['valid_pairs']
        p=paired_p_value(row['regressions'],row['improvements']) if valid else None
        complete=not row['cancelled'] and valid==manifest['samples'] and valid>=manifest['minimum_pairs']
        detected=complete and (row['regressions']-row['improvements'])/valid>=manifest['minimum_effect'] and p<=manifest['alpha']
        if (row.get('p_value')!=p or type(row.get('p_value')) is bool or row['complete']!=complete
            or row['detected']!=detected or row.get('applied_audit_index')!=(manifest['audit_index'] if complete else None)):
            raise ValueError('invalid_outcomes')
        pilot_tasks=row.get('pilot_tasks',[])
        if (not isinstance(pilot_tasks,list) or len(pilot_tasks)>len(allowed_tasks)*4 or
            pilot_tasks and (row['phase']!='pilot' or row['scenario']=='context_truncated')):
            raise ValueError('invalid_outcomes')
        for task in pilot_tasks:
            if (not isinstance(task,dict) or 'difficulty' not in task or task.get('task_kind') not in allowed_tasks
                or task.get('difficulty') not in (None,1,2,3,4)
                or any(type(task.get(field,0)) is not int or not 0<=task.get(field,0)<=manifest['samples']
                       for field in TASK_COUNTS)):
                raise ValueError('invalid_outcomes')
        items=row.get('pilot_items',[])
        if (not isinstance(items,list) or len(items)>manifest['samples']*2 or
            items and (row['phase']!='pilot' or row['scenario']=='context_truncated')):
            raise ValueError('invalid_outcomes')
        seen_items=set()
        from .grading import GRADING_ISSUES,SAFE_TEMPLATES
        allowed_errors=exam.RESPONSE_ISSUES | assessment.RESPONSE_ISSUES | {
            None,'answer_format','recovered_format','authentication_failed','unsupported_parameters',
            'reference_required','invalid_response','reference_model_retired','cancelled','budget_exhausted','local_error',
            'rate_limited','http_error','remote_error','reference_model_unavailable',
            'service_unavailable','endpoint_unavailable','redirect_blocked','response_too_large',
        }
        for item in items:
            if (not isinstance(item,dict) or set(item)!={'question_number','task_kind','template','difficulty','seed',
                    'source_kind','correct','format_state','attempts','error_code','grading_issue'} or
                type(item['question_number']) is not int or not 1<=item['question_number']<=manifest['samples'] or
                item['source_kind'] not in ('relay','reference') or item['task_kind'] not in allowed_tasks or
                not isinstance(item['template'],str) or item['template'] not in SAFE_TEMPLATES or
                type(item['difficulty']) is not int or not 1<=item['difficulty']<=4 or
                type(item['seed']) is not int or not 0<=item['seed']<2**31 or
                item['correct'] is not None and type(item['correct']) is not bool or
                item['format_state'] not in (None,'valid','recovered_format','answer_format') or
                type(item['attempts']) is not int or not 0<=item['attempts']<=1+manifest['retry_policy']['max_retries_per_item'] or
                item['error_code'] is not None and not isinstance(item['error_code'],str) or
                item['grading_issue'] is not None and not isinstance(item['grading_issue'],str) or
                item['error_code'] not in allowed_errors or item['grading_issue'] not in GRADING_ISSUES | {None}):
                raise ValueError('invalid_outcomes')
            item_key=(item['source_kind'],item['question_number'])
            if item_key in seen_items: raise ValueError('invalid_outcomes')
            seen_items.add(item_key)
        if spec and row['phase']=='pilot' and row['scenario']!='context_truncated':
            _checked_exam_pilot_items(manifest,row)
        checked_exam_score_counts(manifest,row)
        checked_trial_failure(manifest,row)


def read_study(directory):
    root=checked_path(directory)
    manifest_path=checked_path(root/'manifest.json')
    if manifest_path.stat().st_size>65536: raise ValueError('invalid_study')
    manifest=json.loads(manifest_path.read_bytes()); validate(manifest)
    path=checked_path(root/'outcomes.json')
    if not path.exists(): return manifest,[]
    if path.stat().st_size>16*1024*1024: raise ValueError('study_too_large')
    records=json.loads(path.read_bytes())
    checked_records(manifest,records)
    return manifest,records
