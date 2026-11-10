"""Shared basic/paired/specialist jobs; all calls go through the budget controller."""
from dataclasses import replace
import secrets

from .suites import cases,SUITES
from .statistics import compare_paired
from .transport import EndpointError
from .families import usable_reference, reasoning_reference


def run_quality(service,monitor,mode,samples,progress,*,seed=None):
    suite='quality' if mode=='quality_audit' else mode
    seed=secrets.randbelow(2**31) if seed is None else seed
    rows=list(cases(suite,40 if mode=='quality_audit' and samples is None else samples,seed=seed))
    paired=mode=='quality_audit'
    reference = reasoning_reference(monitor) if mode == 'reasoning' else usable_reference(monitor)
    if paired and reference is None: raise EndpointError('reference_required')
    settings=('low','high') if mode=='reasoning' else (monitor.target.protocol.reasoning_effort,)
    references=(False,True) if (paired or mode=='reasoning' and reference is not None) else (False,)
    total=len(rows)*len(settings)*len(references)
    reserve=max(len(c.prompt.encode()) for c in rows)+monitor.target.protocol.max_output_tokens+256
    batch=service.store.reserve_batch(total,reserve)
    result={'suite_version':SUITES[suite]['version'],'task_seed':seed,'task_count':len(rows),'sample_count':total,'response_count':0,'network_failures':0,
            'invalid_responses':0,'capability_completed':0,'capability_valid':0,'capability_correct':0,
            'identity_state':'no_reference','detected_anomaly':False}
    progress.update(result)
    service.set_progress(total)
    pairs=[]; by_setting=[]; context_rows=[]
    try:
        if paired:
            index,alpha=service.store.next_audit(); result.update(audit_index=index,alpha=alpha)
            progress.update(audit_index=index,alpha=alpha)
        for effort in settings:
            row_count={'effort':effort,'sample_count':len(rows),'capability_correct':0,'capability_valid':0,'reference_accuracy':None}
            reference_correct=0; reference_valid=0
            configured=replace(monitor,target=replace(monitor.target,protocol=replace(monitor.target.protocol,reasoning_effort=effort)),
                               reference=replace(reference,protocol=replace(reference.protocol,reasoning_effort=effort)) if reference else None)
            for i,case in enumerate(rows):
                values={}
                for is_reference in (references if i%2 else tuple(reversed(references))):
                    if is_reference and monitor.reference_error:
                        continue
                    try:
                        response=service._call(configured,case,reference=is_reference,batch=batch)
                        result['response_count']+=1
                        grade=case.grade(response.text) if response.complete else {'valid':False,'correct':False}
                        values[is_reference]=grade['correct'] if grade['valid'] else None
                        result['invalid_responses']+=not grade['valid']
                        if not is_reference:
                            result['capability_completed']+=1; result['capability_valid']+=grade['valid']; result['capability_correct']+=grade['correct']
                            row_count['capability_valid']+=grade['valid']; row_count['capability_correct']+=grade['correct']
                            if suite=='context': context_rows.append({'context_characters':len(case.prompt),'capability_correct':int(grade['correct']),
                                                                     'capability_valid':int(grade['valid']),'sample_count':1})
                        else:
                            reference_valid+=grade['valid']; reference_correct+=grade['correct']
                    except EndpointError as error:
                        result['network_failures']+=1; result['error_code']=str(error); values[is_reference]=None
                    progress.update(result)
                if paired: pairs.append((values.get(True),values.get(False)))
            row_count['reference_accuracy']=reference_correct/reference_valid if reference_valid==len(rows) else None
            by_setting.append(row_count)
        if paired:
            compared=compare_paired(pairs,alpha=alpha)
            compared['reference_correct'] = sum(ref for ref, actual in pairs if ref is not None and actual is not None)
            compared['target_correct'] = sum(actual for ref, actual in pairs if ref is not None and actual is not None)
            result.update(paired_result=compared,capability_state=compared['status'],detected_anomaly=compared['status']=='degraded')
            if compared['valid_pairs']:
                result['provenance_level'] = 'same_time_official_reference'
        else:
            result['capability_state']='incomplete_comparison' if result['network_failures'] or result['invalid_responses'] else (
                'observed_answers_correct' if result['capability_correct']==result['capability_completed'] else 'screening_failure')
        if mode=='reasoning': result['reasoning_comparison']=by_setting
        if mode=='context': result['context_results']=context_rows
        return result
    finally:
        service.store.release_batch(batch)
        progress.update(result)
