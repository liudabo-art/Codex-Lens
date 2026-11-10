"""Conservative preflight estimates, never an asserted provider billing ceiling."""
import math
from .suites import SUITES
from .families import family_for, matching_reference, reference_state

MODES=('screen','quality','quality_audit','baseline','identity_audit','capability_audit','context','reasoning','assessment')
ASSESSMENT_PROMPT_BYTES = 1536
ASSESSMENT_MAX_RETRIES = 2


def assessment_plan(monitor, samples=None):
    count = 10 if samples is None else samples
    if type(count) is not int or not 1 <= count <= 200:
        raise ValueError('invalid_samples')
    matched = matching_reference(monitor)
    reference_requests = count if matched else 0
    requests = count + reference_requests
    output_bound = monitor.target.protocol.max_output_tokens
    if matched:
        output_bound = max(output_bound, monitor.reference.protocol.max_output_tokens)
    return {
        'mode': 'assessment', 'sample_count': count, 'required_requests': requests,
        'target_requests': count, 'reference_requests': reference_requests,
        'max_retry_requests': requests * ASSESSMENT_MAX_RETRIES,
        'estimated_tokens': requests * (ASSESSMENT_PROMPT_BYTES + output_bound + 256),
        'estimated_cost': None, 'status': 'ok', 'matched_reference': matched,
        'reference_state': reference_state(monitor),
    }


def estimate(mode,samples,protocol,has_reference,prices=None):
    if mode not in MODES or mode == 'assessment': raise ValueError('invalid_mode')
    default={'screen':3,'quality':10,'quality_audit':40,'baseline':12,'identity_audit':50,'capability_audit':40,'context':3,'reasoning':5}[mode]
    n=default if samples is None else samples
    if type(n) is not int or not 1<=n<=200: raise ValueError('invalid_samples')
    required=3 if mode=='screen' else n*(10 if mode=='identity_audit' else 2 if mode in ('quality_audit','capability_audit') else 2*(2 if has_reference else 1) if mode=='reasoning' else 1)
    input_bound=66560 if mode=='context' else 4096
    per_call=input_bound+protocol.max_output_tokens+256
    prices=prices or {}; cost=0.0; valid=True
    reference_calls=n if mode in ('quality_audit','capability_audit') else n*5 if mode=='identity_audit' else n if mode=='baseline' else n*2 if mode=='reasoning' and has_reference else 0
    for count,prefix in ((required-reference_calls,''),(reference_calls,'reference_')):
        if not count: continue
        a,b=prices.get(prefix+'input_price'),prices.get(prefix+'output_price')
        if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=100000 for x in (a,b)):
            valid=False; continue
        cost+=count*(input_bound*a+protocol.max_output_tokens*b)/1000000
    return {'mode':mode,'sample_count':n,'required_requests':required,'estimated_tokens':required*per_call,
            'estimated_cost':cost if valid else None,'currency':'USD','cost_is_estimate':True,
            'status':'reference_required' if mode in ('quality_audit','capability_audit','identity_audit','baseline') and not has_reference else 'ok'}


def support(monitor,baseline=None):
    from datetime import datetime,timezone
    matched=matching_reference(monitor)
    if baseline and not matched:
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(baseline['completed_at'])).total_seconds()
            matched=0<=age<=7*86400 and len(baseline['baseline_features'])>=12
        except (ValueError,KeyError,TypeError): pass
    return {'target_id':monitor.target_id,'model':monitor.target.model,
            'model_family':family_for(monitor.target.model),
            'can_connect':bool(monitor.last_result and monitor.last_result.get('response_count',0)),
            'basic_evaluation':monitor.credential_ready,'matched_reference':matched,
            'calibrated':False,'tools_structured':False}
