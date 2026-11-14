"""Anonymous study counters and descriptive metrics; never model calibration gates."""
from collections import Counter
import math

from .exam_registry import is_exam_suite
from .grading import GRADING_ISSUES


SIDE_FIELDS = frozenset(('sample_count','attempted','completed','correct','format_failures',
                         'format_recovered','retry_requests'))
TRIAL_ERROR_CODES = frozenset((
    'network_error','stream_interrupted','empty_answer','output_limit','response_filtered',
    'incomplete_output','authentication_failed','unsupported_parameters','reference_required',
    'invalid_response','reference_model_retired','local_error','rate_limited','http_error',
    'remote_error','reference_model_unavailable','service_unavailable','endpoint_unavailable',
    'redirect_blocked','response_too_large','cancelled','budget_exhausted',
))


def extract_exam_score_counts(result, samples):
    """Project only known counters; an unstarted exam retains zero progress."""
    sides = {side['source_kind']:side for side in result.get('exam',{}).get('sides',[])}
    return {source:{field:(samples if field=='sample_count' else sides.get(source,{}).get(field,0))
                    for field in SIDE_FIELDS} for source in ('reference','relay')}


def checked_exam_score_counts(manifest, row):
    if 'exam_score_counts' not in row:
        return None
    counts = row['exam_score_counts']
    samples = manifest['samples']
    if (not is_exam_suite(manifest['suite_selection']) or row.get('scenario')=='context_truncated'
            or not isinstance(counts,dict) or set(counts)!={'reference','relay'}):
        raise ValueError('invalid_outcomes')
    for side in counts.values():
        if (not isinstance(side,dict) or set(side)!=SIDE_FIELDS
                or any(type(value) is not int or value<0 for value in side.values())
                or side['sample_count']!=samples
                or not side['correct']+side['format_failures']<=side['completed']<=side['attempted']<=samples
                or side['format_recovered']>side['completed']-side['format_failures']
                or side['retry_requests']>min(samples//5,side['attempted']*manifest['retry_policy']['max_retries_per_item'])):
            raise ValueError('invalid_outcomes')
    if (sum(side['attempted']+side['retry_requests'] for side in counts.values())!=row['requests']
            or sum(side['retry_requests'] for side in counts.values())!=row.get('retry_requests',0)
            or row['complete'] and any(side['completed']!=samples for side in counts.values())):
        raise ValueError('invalid_outcomes')
    reference, relay = counts['reference'], counts['relay']
    valid, regressions, improvements = row['valid_pairs'], row['regressions'], row['improvements']
    # A common number of both-correct pairs must explain both side marginals.
    lower = max(0,reference['correct']-regressions-(reference['completed']-valid),
                relay['correct']-improvements-(relay['completed']-valid))
    upper = min(valid-regressions-improvements,reference['correct']-regressions,
                relay['correct']-improvements)
    if (not max(0,reference['completed']+relay['completed']-samples)<=valid<=min(reference['completed'],relay['completed'])
            or lower>upper):
        raise ValueError('invalid_outcomes')
    if row.get('pilot_items'):
        reconstructed = extract_exam_score_counts({},samples)
        for item in row['pilot_items']:
            side = reconstructed[item['source_kind']]
            side['attempted'] += int(item['attempts']>0)
            side['retry_requests'] += max(0,item['attempts']-1)
            formatting = item['error_code']=='answer_format'
            completed = type(item['correct']) is bool or (formatting and item['grading_issue'] in GRADING_ISSUES)
            side['completed'] += int(completed)
            side['correct'] += int(item['correct'] is True)
            side['format_failures'] += int(formatting)
            side['format_recovered'] += int(item['format_state']=='recovered_format')
        if reconstructed!=counts:
            raise ValueError('invalid_outcomes')
    return counts


def make_trial_failure(code, result, samples):
    """Arbitrary exception text never becomes study evidence."""
    source, question = result.get('failure_source'), result.get('failure_question')
    return {'error_code':code if code in TRIAL_ERROR_CODES else 'remote_error',
            'source_kind':source if source in ('reference','relay') else None,
            'question_number':question if type(question) is int and 1<=question<=samples else None}


def checked_trial_failure(manifest, row):
    if 'trial_failure' not in row:
        return None
    failure = row['trial_failure']
    if (not isinstance(failure,dict) or set(failure)!={'error_code','source_kind','question_number'}
            or not isinstance(failure['error_code'],str) or failure['error_code'] not in TRIAL_ERROR_CODES
            or failure['source_kind'] not in (None,'relay','reference')
            or failure['question_number'] is not None and (type(failure['question_number']) is not int
                or not 1<=failure['question_number']<=manifest['samples'])
            or row['complete'] or row['detected']
            or (failure['error_code']=='cancelled')!=row['cancelled']
            or (failure['error_code']=='budget_exhausted')!=(row.get('stop_reason')=='budget_exhausted')):
        raise ValueError('invalid_outcomes')
    return failure


def _distribution(values):
    n = len(values)
    mean = math.fsum(values)/n if n else None
    return {'count':n,'min':min(values) if n else None,'max':max(values) if n else None,
            'mean':mean,'sample_stddev':math.sqrt(math.fsum((value-mean)**2 for value in values)/(n-1)) if n>1 else None}


def _evidence_state(present, total):
    return 'unavailable' if not present else 'partial' if present<total else 'available'


def quality_metrics(manifest, rows):
    """Describe both phases separately; missing old evidence never becomes a score."""
    result = {'schema_version':1}
    for phase in ('pilot','validation'):
        selected = [row for row in rows if row['phase']==phase]
        n = len(selected)
        complete = sum(row['complete'] for row in selected)
        with_counts = [row for row in selected if 'exam_score_counts' in row]
        scored = [row for row in with_counts if row['complete']]
        reference = [100*row['exam_score_counts']['reference']['correct']/manifest['samples'] for row in scored]
        relay = [100*row['exam_score_counts']['relay']['correct']/manifest['samples'] for row in scored]
        failures = [row['trial_failure'] for row in selected if not row['complete'] and 'trial_failure' in row]
        failure_counts = Counter((failure['error_code'],failure['source_kind']) for failure in failures)
        planned = manifest['pilot_trials'] if phase=='pilot' else manifest['trials']
        result[phase] = {
            'planned_trials':planned,'recorded_trials':n,'missing_trials':planned-n,
            'complete_trials':complete,'incomplete_trials':n-complete,
            'completion_rate':complete/n if n else None,'inconclusive_rate':(n-complete)/n if n else None,
            'score_evidence':{'state':_evidence_state(len(with_counts),n) if is_exam_suite(manifest['suite_selection']) else 'not_applicable',
                              'recorded_with_counts':len(with_counts),'missing_counts':n-len(with_counts),
                              'complete_with_counts':len(scored)},
            'repeat_scores':{'reference':_distribution(reference),'relay':_distribution(relay),
                             'gap':_distribution([ref-target for ref,target in zip(reference,relay)])},
            'usage':{**{field:sum(row.get(field,0) for row in selected) for field in
                        ('requests','retry_requests','reported_tokens','estimated_tokens','unknown_usage')},
                     'estimated_cost':None},
            'failure_evidence':{'state':_evidence_state(len(failures),n-complete) if n>complete else 'not_needed',
                                'recorded_with_counts':len(failures),'missing_counts':n-complete-len(failures)},
            'failure_counts':[{'error_code':code,'source_kind':source,'trials':count}
                              for (code,source),count in sorted(failure_counts.items(),key=lambda item:(item[0][0],item[0][1] or ''))],
        }
    return result
