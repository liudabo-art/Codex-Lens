import unittest

from relay_auditor.exporting import html_report
from relay_auditor.reports import explain, trend


def record(**changes):
    row = dict(schema_version=2, target_id='a'*32, source_alias='relay-1', source_kind='relay',
               model='gpt-test', mode='assessment', status='ok', suite_version='assessment-v3',
               evaluated_at='2026-11-09T00:00:00+00:00', task_seed=0, task_count=10,
               capability_completed=10, capability_valid=10, capability_correct=8,
               sample_count=10, reference_state='reference_key_required')
    return row | changes


class ReportFeedbackTests(unittest.TestCase):
    def test_one_sided_test_never_claims_equal_quality(self):
        brief = explain(record(reference_state='reference_matched', paired_result=dict(
            valid_pairs=100, attempted_pairs=100, planned_pairs=100, target_correct=100,
            reference_correct=40, accuracy_loss=-.6, regressions=0, status='no_detected_degradation')))
        self.assertEqual(brief['headline'], '本轮未检出中转能力下降')
        self.assertIn('高 60 个百分点', brief['observed'])

    def test_unpaired_report_explains_missing_reference_and_next_step(self):
        brief = explain(record())
        self.assertIn('未配置', brief['comparison'])
        self.assertIn('官方参考', brief['next_step'])
        self.assertEqual(brief['evaluated_at'], '2026-11-09T00:00:00+00:00')

    def test_partial_report_keeps_scores_coverage_and_loss_bounds(self):
        brief = explain(record(status='cancelled', paired_result=dict(valid_pairs=4, attempted_pairs=5,
            planned_pairs=10, target_correct=2, reference_correct=4, accuracy_loss=.5,
            status='incomplete_comparison', loss_bounds=[-.4, .8]), assessment_counts=[dict(
                source_kind='relay', attempted=5, sample_count=10, valid=4, correct=2)],
            response_issues=[dict(source_kind='reference', error_code='rate_limited', sample_count=1)]))
        self.assertIn('取消', brief['headline'])
        self.assertIn('2/4', brief['observed'])
        self.assertIn('4/10', ' '.join(brief['coverage']))
        self.assertIn('不是置信区间', ' '.join(brief['details']))
        self.assertIn('官方参考', brief['diagnostics'][0])
        self.assertIn('完整', brief['next_step'])

    def test_recovered_format_is_not_reported_as_unscorable(self):
        brief = explain(record(response_issues=[dict(source_kind='relay', error_code='recovered_format', sample_count=2)]))
        self.assertEqual(brief['diagnostics'], [])
        self.assertIn('2', brief['format_notes'][0])
        self.assertIn('已评分', brief['format_notes'][0])

    def test_old_pair_without_loss_and_grouped_skills_use_observed_scores(self):
        brief = explain(record(reference_state='reference_matched', paired_result=dict(valid_pairs=4,
            attempted_pairs=4, target_correct=2, reference_correct=4, status='insufficient_data'),
            assessment_tasks=[dict(task_kind='code_branch', difficulty=i, attempted=2,valid=2,correct=1,
                valid_pairs=2,target_correct=1,reference_correct=2) for i in (1,2)]))
        self.assertIn('低 50 个百分点', brief['observed'])
        self.assertEqual(brief['score_tiles'], [{'label':'中转','score':'2/4'}, {'label':'官方','score':'4/4'}])
        self.assertEqual(len(brief['task_summary']), 1)
        self.assertIn('低 50 个百分点', brief['task_summary'][0])
        self.assertEqual(len(brief['task_details']), 2)

    def test_task_summary_starts_with_largest_observed_gap_and_plain_reference_note(self):
        brief = explain(record(reference_state='reference_matched', reference_model='gpt-test', paired_result=dict(
            valid_pairs=6, attempted_pairs=6, target_correct=3, reference_correct=6, status='insufficient_data'),
            assessment_tasks=[dict(task_kind=kind, attempted=3, valid=3, correct=score,
                valid_pairs=3, target_correct=score, reference_correct=3)
                for kind, score in (('code_branch', 2), ('repair_edges', 1))]))
        self.assertIn('低 66.7 个百分点', brief['task_summary'][0])
        self.assertIn('gpt-test', brief['reference_note'])
        self.assertNotIn('3/6', brief['reference_note'])

    def test_export_preserves_every_record_shared_copy_and_specialist_results(self):
        first = record(assessment_tasks=[dict(task_kind='code_branch',difficulty=2,attempted=3,valid=2,correct=1)])
        second = record(mode='reasoning', task_seed=20, reasoning_comparison=[dict(effort='low', capability_correct=2,sample_count=5)])
        report = html_report({'history':[first,second]})
        for row in (first,second):
            brief = explain(row)
            for key in ('headline','observed','next_step'):
                self.assertIn(brief[key], report)
        self.assertIn('分支', report)
        self.assertIn('low', report)
        self.assertNotIn('尚无质量体检记录', report)

    def test_v3_trend_requires_nonoverlapping_completed_task_ranges(self):
        def rows(seeds):
            return [record(task_seed=seed, evaluated_at=f'2026-11-09T00:00:0{i}+00:00',
                           capability_correct=10 if i<2 else 8) for i,seed in enumerate(seeds)]
        self.assertEqual(trend(rows([0,1,2,3]))['status'], 'insufficient_data')
        self.assertEqual(trend(rows([0,10,20,30]))['status'], 'historical_decline_signal')
        incomplete=rows([0,10,20,30]); incomplete[-1]['capability_completed']=9; incomplete[-1]['capability_valid']=9
        self.assertEqual(trend(incomplete)['status'], 'not_comparable')
        missing=rows([0,10,20,30]); missing[-1].pop('task_count')
        self.assertEqual(trend(missing)['status'], 'not_comparable')


if __name__ == '__main__':
    unittest.main()
