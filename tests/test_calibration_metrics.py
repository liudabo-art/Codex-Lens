"""Offline study evidence is descriptive, anonymous and never imputes old scores."""
import copy
import math
import unittest

from relay_auditor.calibration_metrics import (
    extract_exam_score_counts, checked_exam_score_counts, make_trial_failure,
    checked_trial_failure, quality_metrics,
)


def manifest():
    return {'family':'gpt','suite_selection':'exam-v2','suite_version':'exam-v2',
            'samples':120,'pilot_trials':10,'trials':100,
            'retry_policy':{'max_retries_per_item':2}}


def counts(correct=100, completed=120, attempted=120):
    return dict(sample_count=120,attempted=attempted,completed=completed,correct=correct,
                format_failures=0,format_recovered=0,retry_requests=0)


def row(**changes):
    result=dict(phase='validation',complete=True,cancelled=False,detected=False,
                requests=240,retry_requests=0,reported_tokens=7200,estimated_tokens=400000,
                unknown_usage=0,valid_pairs=120,regressions=20,improvements=0,
                exam_score_counts={'reference':counts(100),'relay':counts(80)})
    result.update(changes)
    return result


class CalibrationMetricsTests(unittest.TestCase):
    def test_extract_projects_only_bounded_anonymous_counter_fields(self):
        source={'exam':{'sides':[{'source_kind':'relay',**counts(80),'PRIVATE-EXTRA':'synthetic'},
                                 {'source_kind':'reference',**counts(100)}]},'PRIVATE-EXTRA':'synthetic'}
        value=extract_exam_score_counts(source,120)
        self.assertEqual(value,{'relay':counts(80),'reference':counts(100)})
        value['relay']['correct']=1
        self.assertEqual(source['exam']['sides'][0]['correct'],80)
        empty=extract_exam_score_counts({},120)
        self.assertEqual(empty['relay'],counts(0,0,0))

    def test_complete_counts_reconcile_scores_pairs_and_retry_requests(self):
        outcome=row(requests=242,retry_requests=2)
        outcome['exam_score_counts']['relay']['retry_requests']=2
        outcome['exam_score_counts']['relay']['format_failures']=5
        outcome['exam_score_counts']['reference']['format_recovered']=2
        self.assertEqual(checked_exam_score_counts(manifest(),outcome),outcome['exam_score_counts'])
        for side,field,value in (('relay','correct',81),('relay','completed',119),
                                ('relay','sample_count',180),('relay','correct',True),
                                ('relay','format_failures',41),('reference','format_recovered',121),
                                ('relay','retry_requests',1)):
            bad=copy.deepcopy(outcome); bad['exam_score_counts'][side][field]=value
            with self.subTest(field=field,value=value),self.assertRaisesRegex(ValueError,'invalid_outcomes'):
                checked_exam_score_counts(manifest(),bad)

    def test_partial_marginals_require_a_feasible_same_question_overlap(self):
        value=row(complete=False,requests=9,valid_pairs=4,regressions=1,improvements=0,
                  exam_score_counts={'reference':counts(4,4,4),'relay':counts(4,5,5)})
        self.assertEqual(checked_exam_score_counts(manifest(),value),value['exam_score_counts'])
        bad=copy.deepcopy(value); bad['exam_score_counts']['relay']['correct']=2
        with self.assertRaisesRegex(ValueError,'invalid_outcomes'):
            checked_exam_score_counts(manifest(),bad)
        bad=copy.deepcopy(value); bad['exam_score_counts']['reference']['completed']=3
        with self.assertRaisesRegex(ValueError,'invalid_outcomes'):
            checked_exam_score_counts(manifest(),bad)

    def test_complete_format_losses_are_zero_score_evidence_not_missing_answers(self):
        value=row(regressions=0,exam_score_counts={'reference':counts(0),'relay':counts(0)})
        for side in value['exam_score_counts'].values(): side['format_failures']=120
        checked_exam_score_counts(manifest(),value)
        report=quality_metrics(manifest(),[value])['validation']
        self.assertEqual(report['repeat_scores']['relay']['mean'],0)
        self.assertEqual(report['repeat_scores']['gap']['mean'],0)
        self.assertEqual(report['completion_rate'],1)

    def test_pilot_items_must_reproduce_the_same_side_counters(self):
        item=lambda source,correct:dict(source_kind=source,attempts=1,correct=correct,
                                        format_state='valid',error_code=None,grading_issue=None)
        value=row(phase='pilot',complete=False,requests=2,valid_pairs=1,regressions=1,
                  exam_score_counts={'reference':counts(1,1,1),'relay':counts(0,1,1)},
                  pilot_items=[item('reference',True),item('relay',False)])
        checked_exam_score_counts(manifest(),value)
        value['pilot_items'][1]['correct']=True
        with self.assertRaisesRegex(ValueError,'invalid_outcomes'):
            checked_exam_score_counts(manifest(),value)

    def test_old_missing_evidence_and_nonexam_compatibility_never_impute_zero(self):
        old=row(); old.pop('exam_score_counts')
        self.assertIsNone(checked_exam_score_counts(manifest(),old))
        report=quality_metrics(manifest(),[old])['validation']
        self.assertEqual(report['score_evidence']['missing_counts'],1)
        self.assertEqual(report['repeat_scores']['relay']['count'],0)
        self.assertIsNone(report['repeat_scores']['relay']['mean'])
        for change in ({'suite_selection':'assessment-v4'}, {'samples':180}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,'invalid_outcomes'):
                checked_exam_score_counts(manifest()|change,row())

    def test_phase_metrics_keep_failures_usage_and_complete_score_variation_separate(self):
        second=row(exam_score_counts={'reference':counts(110),'relay':counts(100)},
                   regressions=10)
        incomplete=row(complete=False,cancelled=True,requests=0,valid_pairs=0,regressions=0,
                       exam_score_counts={'reference':counts(0,0,0),'relay':counts(0,0,0)},
                       trial_failure={'error_code':'cancelled','source_kind':None,'question_number':None},
                       reported_tokens=0,unknown_usage=1,estimated_tokens=500)
        pilot=row(phase='pilot')
        report=quality_metrics(manifest(),[row(),second,incomplete,pilot])
        validation=report['validation']
        self.assertEqual((validation['planned_trials'],validation['recorded_trials'],validation['missing_trials']),(100,3,97))
        self.assertEqual(validation['completion_rate'],2/3)
        self.assertEqual(validation['inconclusive_rate'],1/3)
        scores=validation['repeat_scores']['relay']
        values=[100*80/120,100*100/120]
        self.assertEqual(scores['count'],2)
        self.assertAlmostEqual(scores['mean'],sum(values)/2)
        self.assertAlmostEqual(scores['sample_stddev'],abs(values[0]-values[1])/math.sqrt(2))
        self.assertEqual(validation['usage'],dict(requests=480,retry_requests=0,reported_tokens=14400,
                                                estimated_tokens=800500,unknown_usage=1,estimated_cost=None))
        self.assertEqual(validation['failure_counts'],[{'error_code':'cancelled','source_kind':None,'trials':1}])
        self.assertEqual(report['pilot']['recorded_trials'],1)
        empty=quality_metrics(manifest(),[])['validation']
        self.assertIsNone(empty['completion_rate'])
        self.assertIsNone(empty['repeat_scores']['gap']['sample_stddev'])

    def test_cancelled_last_answer_never_becomes_a_final_score(self):
        cancelled=row(complete=False,cancelled=True)
        report=quality_metrics(manifest(),[cancelled])['validation']
        self.assertEqual(report['repeat_scores']['relay']['count'],0)
        self.assertEqual(report['score_evidence']['recorded_with_counts'],1)
        self.assertEqual(report['failure_evidence']['missing_counts'],1)

    def test_trial_failure_projects_fixed_codes_and_rejects_contradictions(self):
        failure=make_trial_failure('PRIVATE-SYNTHETIC-ERROR',{'failure_source':'relay','failure_question':3},120)
        self.assertEqual(failure,{'error_code':'remote_error','source_kind':'relay','question_number':3})
        incomplete=row(complete=False,valid_pairs=4,trial_failure=failure)
        self.assertEqual(checked_trial_failure(manifest(),incomplete),failure)
        for change in ({'complete':True},{'cancelled':True},{'stop_reason':'budget_exhausted'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,'invalid_outcomes'):
                checked_trial_failure(manifest(),incomplete|change)
        budget=incomplete|{'stop_reason':'budget_exhausted','trial_failure':failure|{'error_code':'budget_exhausted'}}
        checked_trial_failure(manifest(),budget)
        bad=copy.deepcopy(budget); bad['trial_failure']['question_number']=True
        with self.assertRaisesRegex(ValueError,'invalid_outcomes'): checked_trial_failure(manifest(),bad)
        bad=copy.deepcopy(budget); bad['trial_failure']['private']='synthetic'
        with self.assertRaisesRegex(ValueError,'invalid_outcomes'): checked_trial_failure(manifest(),bad)


if __name__=='__main__': unittest.main()
