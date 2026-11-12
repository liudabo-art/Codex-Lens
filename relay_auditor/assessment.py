"""One-button assessment with independently counted responses on each side."""
from collections import Counter
import re
import secrets

from .families import family_for, reference_issue, PROFILES, GENERIC
from .grading import grade_answer, item_result
from .planning import assessment_plan, ASSESSMENT_MAX_RETRIES, ASSESSMENT_PROMPT_BYTES
from .statistics import MINIMUM_PAIRED_SAMPLES, compare_paired, spending_alpha
from .storage import BudgetExceeded
from .suites import quality_case
from .transport import EndpointError

VERSION = 'assessment-v4'
RESPONSE_ISSUES = frozenset(('output_limit', 'stream_interrupted', 'empty_answer', 'response_filtered', 'incomplete_output'))
RETRYABLE = frozenset(('network_error', 'stream_interrupted'))
STOP_REASONS = RETRYABLE | {'authentication_failed', 'unsupported_parameters', 'output_limit'}
RETRY_DELAYS = (1, 2)
JSON_FENCE = re.compile(r'```(?:json)?[ \t]*\r?\n(.+?)\r?\n```', re.IGNORECASE | re.DOTALL)
DIFFICULTY_TASKS = frozenset(('code', 'constraints', 'document', 'code_branch', 'repair_edges', 'constraints_multi'))


def assessment_cases(model, samples, seed):
    tasks = PROFILES.get(family_for(model), GENERIC).tasks
    for index in range(samples):
        difficulty = 1 + (index // len(tasks)) % 4
        yield quality_case(tasks[index % len(tasks)], seed + index, difficulty=difficulty), difficulty


def assessment_comparison(pairs, planned_pairs, *, alpha=None):
    """Use complete pairs for the test and every planned slot for missingness bounds."""
    pairs = list(pairs)
    comparison = compare_paired(pairs, alpha=spending_alpha(1) if alpha is None else alpha)
    valid = [(ref, target) for ref, target in pairs if type(ref) is bool and type(target) is bool]
    comparison.update(planned_pairs=planned_pairs, alpha=alpha,
                      reference_correct=sum(ref for ref, _ in valid), target_correct=sum(target for _, target in valid))
    if len(valid) < planned_pairs:
        unstarted = planned_pairs - len(pairs)
        lower = sum((ref is True) - (target is not False) for ref, target in pairs) - unstarted
        upper = sum((ref is not False) - (target is True) for ref, target in pairs) + unstarted
        comparison.update(status='incomplete_comparison', loss_bounds=[lower / planned_pairs, upper / planned_pairs])
    elif alpha is None:
        comparison['status'] = 'insufficient_data'
    return comparison


def run_assessment(service, monitor, samples, result, *, seed=None, recover=False):
    plan = assessment_plan(monitor, samples)
    seed = secrets.randbelow(2**31) if seed is None else seed
    cases = list(assessment_cases(monitor.target.model, plan['sample_count'], seed))
    paired = plan['matched_reference']
    longest = max(len(case.prompt.encode()) for case, _ in cases)
    if longest > ASSESSMENT_PROMPT_BYTES:
        raise EndpointError('invalid_synthetic_case')
    counts = {
        source: dict(source_kind=source, sample_count=len(cases), attempted=0, response_count=0, valid=0, correct=0)
        for source in ((monitor.target.role, 'reference') if paired else (monitor.target.role,))
    }
    target_counts = counts[monitor.target.role]
    items = {(case.seed, source): item_result(case, difficulty, index, source)
             for index, (case, difficulty) in enumerate(cases, 1) for source in counts}
    result.update(
        suite_version=VERSION, model_family=family_for(monitor.target.model), task_seed=seed, task_count=len(cases),
        sample_count=plan['required_requests'], reference_state=plan['reference_state'],
        reference_error=reference_issue(monitor),
        capability_attempted=0, capability_completed=0, capability_valid=0, capability_correct=0,
        response_count=0, network_failures=0, invalid_responses=0, retry_requests=0,
        identity_state='not_tested', assessment_tasks=[], assessment_counts=list(counts.values()), response_issues=[],
        item_results=list(items.values()), grading_issues=[],
    )
    diagnostics = Counter()
    grading_diagnostics = Counter()
    task_rows = {}
    pairs = []
    audit_index = alpha = None
    max_retries = ASSESSMENT_MAX_RETRIES if recover else 0
    output_bound = monitor.target.protocol.max_output_tokens
    if paired:
        output_bound = max(output_bound, monitor.reference.protocol.max_output_tokens)
    batch = service.store.reserve_batch(plan['required_requests'], longest + output_bound + 256)
    service.set_progress(plan['required_requests'])

    def request(case, reference, side, row):
        previous_issue = None
        item = items[case.seed, side['source_kind']]
        try:
            for attempt in range(max_retries + 1):
                completed_before = service.progress.get('completed', 0)
                response = error_code = None
                try:
                    response = service._call(monitor, case, reference=reference, batch=None if attempt else batch)
                except EndpointError as error:
                    error_code = str(error)
                except BudgetExceeded:
                    if previous_issue:
                        result['failure_source'] = side['source_kind']
                        diagnostics[(reference, previous_issue)] += 1
                    raise
                finally:
                    sent = service.progress.get('completed', 0) > completed_before
                    item['attempts'] += int(sent)
                    if sent and attempt:
                        result['retry_requests'] += 1
                        side['retry_requests'] = side.get('retry_requests', 0) + 1
                        service.set_progress(plan['required_requests'] + result['retry_requests'])
                    elif sent:
                        side['attempted'] += 1
                        if not reference:
                            row['attempted'] += 1
                issue = error_code if response is None else response.issue
                if not sent or issue not in RETRYABLE or attempt == max_retries:
                    return response, error_code, sent
                previous_issue = issue
                service.set_retry_progress({'retry_question': case.seed - seed + 1,
                                            'retry_attempt': attempt + 1, 'source_kind': side['source_kind']})
                service.wait_for_retry(monitor, RETRY_DELAYS[attempt])
        finally:
            if previous_issue:
                service.set_retry_progress(None)

    def read(case, reference, row):
        if reference and result.get('reference_error'):
            return None
        side = counts['reference'] if reference else target_counts
        item = items[case.seed, side['source_kind']]
        response, error_code, sent = request(case, reference, side, row)
        if response is None:
            item['error_code'] = error_code
            if sent:
                result['network_failures'] += 1
            diagnostics[(reference, error_code)] += 1
            if reference and monitor.reference_error:
                result['reference_error'] = monitor.reference_error
            if recover and error_code in STOP_REASONS:
                result['failure_source'] = side['source_kind']
                raise EndpointError(error_code)
            return None
        side['response_count'] += 1
        result['response_count'] += 1
        issue = response.issue if response.issue in RESPONSE_ISSUES else None
        if not response.complete:
            issue = issue or 'incomplete_output'
        elif not response.text.strip():
            issue = 'empty_answer'
        if not issue:
            grade = grade_answer(case, response.text)
            item.update(grade)
            if grade['format_state'] != 'answer_format':
                if grade['format_state'] == 'recovered_format':
                    diagnostics[(reference, 'recovered_format')] += 1
                side['valid'] += 1
                side['correct'] += grade['correct']
                if not reference:
                    row['valid'] += 1
                    row['correct'] += grade['correct']
                return grade['correct']
            issue = 'answer_format'
            grading_diagnostics[side['source_kind'], grade['grading_issue']] += 1
        item['error_code'] = issue
        diagnostics[(reference, issue)] += 1
        result['invalid_responses'] += 1
        if recover and issue in STOP_REASONS:
            result['failure_source'] = side['source_kind']
            raise EndpointError(issue)
        return None

    try:
        for index, (case, difficulty) in enumerate(cases):
            level = difficulty if case.kind in DIFFICULTY_TASKS else None
            row = task_rows.setdefault((case.kind, level), {
                'task_kind': case.kind, 'difficulty': level, 'attempted': 0, 'valid': 0, 'correct': 0,
            })
            sides = ((True, False) if index % 2 else (False, True)) if paired else (False,)
            attempted_before = sum(side['attempted'] for side in counts.values())
            answers = {}
            try:
                for reference in sides:
                    answers[reference] = read(case, reference, row)
            finally:
                if paired and sum(side['attempted'] for side in counts.values()) > attempted_before:
                    official, actual = answers.get(True), answers.get(False)
                    pairs.append((official, actual))
                    if official is not None and actual is not None:
                        row['valid_pairs'] = row.get('valid_pairs', 0) + 1
                        row['reference_correct'] = row.get('reference_correct', 0) + int(official)
                        row['target_correct'] = row.get('target_correct', 0) + int(actual)
        if paired:
            # Descriptive screens and incomplete runs cannot reject, so spend no formal decision budget.
            if (len(pairs) == len(cases) and len(pairs) >= MINIMUM_PAIRED_SAMPLES
                and all(ref is not None and actual is not None for ref, actual in pairs)):
                audit_index, alpha = service.store.next_audit()
        else:
            result['capability_state'] = ('insufficient_data' if not target_counts['valid'] else
                'incomplete_comparison' if target_counts['valid'] < len(cases) else
                'observed_answers_correct' if target_counts['correct'] == len(cases) else 'screening_failure')
        return result
    finally:
        if paired:
            comparison = assessment_comparison(pairs, len(cases), alpha=alpha)
            result.update(paired_result=comparison, capability_state=comparison['status'],
                          detected_anomaly=comparison['status'] == 'degraded', audit_index=audit_index)
            if comparison['valid_pairs']:
                result['provenance_level'] = 'same_time_official_reference'
        result.update(capability_attempted=target_counts['attempted'], capability_completed=target_counts['response_count'],
                      capability_valid=target_counts['valid'], capability_correct=target_counts['correct'])
        result['assessment_tasks'] = list(task_rows.values())
        result['response_issues'] = [
            {'source_kind': 'reference' if reference else monitor.target.role, 'error_code': issue, 'sample_count': count}
            for (reference, issue), count in diagnostics.items()
        ]
        result['grading_issues'] = [
            {'source_kind': source, 'grading_issue': issue, 'sample_count': count}
            for (source, issue), count in grading_diagnostics.items()
        ]
        service.store.release_batch(batch)
