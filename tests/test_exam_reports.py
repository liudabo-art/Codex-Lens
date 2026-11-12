import json
import unittest

from relay_auditor.exporting import html_report
from relay_auditor.reports import comparisons, explain, trend, upgrade
from relay_auditor.statistics import paired_p_value
from relay_auditor.storage import safe_snapshot


def exam_record():
    sides = [
        dict(source_kind=side, sample_count=120, attempted=120, completed=120,
             correct=correct, format_failures=2, format_recovered=1, retry_requests=1)
        for side, correct in (('relay', 91), ('reference', 105))
    ]
    sections = []
    for side in ('relay', 'reference'):
        for kind in ('exam_reasoning', 'exam_code', 'exam_repair', 'exam_information', 'exam_structure'):
            for difficulty in range(1, 4):
                correct = 7 if side == 'reference' else 6
                if side == 'relay' and kind == 'exam_code' and difficulty == 1:
                    correct += 2
                if side == 'relay' and kind == 'exam_repair' and difficulty == 3:
                    correct -= 1
                sections.append(dict(source_kind=side, task_kind=kind, difficulty=difficulty,
                                     sample_count=8, completed=8, correct=correct,
                                     format_failures=0, format_recovered=0))
    return dict(schema_version=2, target_id='b' * 32, source_alias='relay-2', source_kind='relay',
                mode='capability_exam', suite_version='exam-v1', status='ok', task_count=120, task_seed=17,
                model='gpt-test', reference_model='gpt-test', capability_valid=120, capability_completed=120,
                capability_correct=91, comparison_conditions={'reasoning_effort': 'high', 'wire_api': 'responses'},
                reference_comparison_conditions={'reasoning_effort': 'high', 'wire_api': 'responses'},
                evaluated_at='2026-11-10T10:00:00+00:00', provenance_level='same_time_official_reference',
                exam=dict(comparison='paired', submitted=True, sides=sides, sections=sections),
                paired_result=dict(status='degraded', valid_pairs=120, target_correct=91, reference_correct=105,
                                   regressions=15, improvements=1, p_value=.00026, alpha=.005))


class ExamReportsTests(unittest.TestCase):
    def test_item_evidence_keeps_unstarted_and_failed_requests_out_of_format_losses(self):
        from relay_auditor.reports import item_evidence
        record={'item_results':[
            {'question_number':1,'source_kind':'relay','correct':None,'format_state':'answer_format','attempts':0,'error_code':None},
            {'question_number':2,'source_kind':'relay','correct':None,'format_state':'answer_format','attempts':3,'error_code':'network_error'},
            {'question_number':3,'source_kind':'relay','correct':None,'format_state':'answer_format','attempts':1,'error_code':'answer_format'},
        ]}
        lines=item_evidence(record)
        self.assertIn('未作答',lines[0])
        self.assertIn('请求未完成',lines[1])
        self.assertIn('格式失分',lines[2])

    def test_reliability_counts_attempts_including_retries(self):
        row = exam_record()
        row.update(sample_count=240, response_count=242)
        self.assertEqual(upgrade(row)['dimensions']['reliability']['sample_count'], 242)
        row.update(status='unavailable', response_count=121)
        row['exam']['submitted'] = False
        row['exam']['sides'][0].update(attempted=60, retry_requests=1)
        row['exam']['sides'][1].update(attempted=59, retry_requests=1)
        self.assertEqual(upgrade(row)['dimensions']['reliability']['sample_count'], 121)

    def test_full_score_and_gap_are_consistent_in_presenter_and_html(self):
        row = exam_record()
        view = explain(row)
        self.assertEqual(view['headline'], '本场同条件下，中转表现明显低于官方')
        self.assertIn('75.8 分', view['observed'])
        self.assertIn('87.5 分', view['observed'])
        self.assertIn('11.7 个百分点', view['observed'])
        self.assertIn('边界纠错', view['observed'])
        self.assertIn('挑战', ' '.join(view['task_summary']))
        self.assertIn('格式失分 2', ' '.join(view['format_notes']))
        self.assertIsNone(upgrade(row)['dimensions']['quality']['interval'])
        rendered = html_report({'history': [row]})
        for key in ('headline', 'observed', 'next_step'):
            self.assertIn(view[key], rendered)
        self.assertIn('能力考试 · 标准卷', rendered)

    def test_large_observed_gap_does_not_override_pairing_threshold(self):
        row = exam_record()
        row['paired_result'].update(status='inconclusive', regressions=29, improvements=15,
                                    p_value=paired_p_value(29, 15))
        view = explain(row)
        self.assertEqual(view['headline'], '能力考试已交卷')
        self.assertIn('11.7 个百分点', view['observed'])
        self.assertIn('未达到判定', view['reference_note'])

    def test_paired_failure_hides_all_final_scores_even_if_relay_finished(self):
        row = exam_record()
        row.update(status='unavailable', failure_source='reference', failure_question=120,
                   error_code='stream_interrupted')
        row['exam']['submitted'] = False
        row['exam']['sides'][1]['completed'] = 119
        view = explain(row)
        self.assertIn('未交卷', view['headline'])
        self.assertIn('官方参考第 120 题', ' '.join(view['diagnostics']))
        self.assertIn('119/120', ' '.join(view['coverage']))
        self.assertEqual(view['score_tiles'], [])
        self.assertEqual(view['task_summary'], [])
        self.assertIsNone(upgrade(row)['dimensions']['quality']['accuracy'])
        self.assertNotIn('75.8 分', html_report({'history': [row]}))

    def test_single_side_score_and_paired_evidence_are_separate(self):
        row = exam_record()
        row['exam']['comparison'] = 'relay_only'
        row['exam']['sides'].pop()
        row['exam']['sections'] = [section for section in row['exam']['sections'] if section['source_kind'] == 'relay']
        row.pop('paired_result')
        view = explain(row)
        self.assertEqual(view['headline'], '能力考试已交卷')
        self.assertIn('75.8 分', view['observed'])
        self.assertIn('仅评估中转', view['reference_note'])
        self.assertIn('官方参考', view['next_step'])

    def test_anonymous_snapshot_keeps_exam_aggregates_and_filters_private_data(self):
        row = exam_record()
        row['exam'].update(api_key='private-example-token', prompt='private-example-prompt')
        row['exam']['sides'][0]['raw_response'] = 'private-example-answer'
        row['exam_plan_id'] = 'example-confirmation-token'
        safe = safe_snapshot(row)
        self.assertEqual(safe['mode'], 'capability_exam')
        self.assertEqual(safe['suite_version'], 'exam-v1')
        self.assertEqual(safe['exam']['comparison'], 'paired')
        self.assertEqual(safe['exam']['sections'][0]['task_kind'], 'exam_reasoning')
        self.assertEqual(safe['exam']['sides'][0]['format_failures'], 2)
        serialized = json.dumps(safe)
        self.assertNotIn('private-example', serialized)
        self.assertNotIn('exam_plan_id', serialized)

    def test_exam_records_do_not_displace_routine_trend_or_comparison(self):
        recent_exam = exam_record()
        routines = [
            dict(target_id=recent_exam['target_id'], model='gpt-test', status='ok', mode='assessment',
                 suite_version='assessment-v3', task_count=10, task_seed=i * 10, sample_count=10,
                 capability_completed=10, capability_valid=10, capability_correct=10,
                 evaluated_at=f'2026-11-10T01:00:0{i}+00:00')
            for i in range(4)
        ]
        self.assertEqual(trend([*routines, recent_exam]), trend(routines))
        self.assertEqual(comparisons([*routines, recent_exam]), comparisons(routines))


if __name__ == '__main__':
    unittest.main()
