import copy
import unittest
from relay_auditor.exporting import html_report
from relay_auditor.reports import explain, upgrade
from relay_auditor.storage import safe_snapshot
from test_exam_reports import exam_record

class FamilyExamReportsTests(unittest.TestCase):
    def test_each_family_version_survives_anonymous_roundtrip_and_shared_report(self):
        for family,version in [('gpt','exam-v2'),('deepseek','exam-v2'),('claude','claude-exam-v1'),('gemini','gemini-exam-v1')]:
            with self.subTest(family=family):
                row=exam_record();row.update(suite_version=version,model_family=family,model=family+'-synthetic',reference_model=family+'-synthetic')
                saved=safe_snapshot(row);self.assertEqual(saved['suite_version'],version)
                view=explain(saved);self.assertEqual(explain(upgrade(saved))['headline'],view['headline'])
                self.assertIn(view['headline'],html_report({'schema_version':2,'history':[saved]}))
                self.assertTrue(any(version in line for line in view['details']))

    def test_higher_target_score_has_clear_direction_and_does_not_claim_inferiority(self):
        row=exam_record();row['exam']['sides'][0]['correct']=110
        row['paired_result'].update(status='no_detected_degradation',target_correct=110,regressions=1,improvements=6,p_value=.99)
        view=explain(row)
        self.assertIn('中转高',view['observed'])
        self.assertIn('本场中转答对更多',view['reference_note'])
        self.assertNotIn('明显低于',view['headline'])

    def test_equal_scores_explain_equal_observation_and_identity_limit(self):
        row=exam_record();row['exam']['sides'][0]['correct']=105
        row['paired_result'].update(status='no_detected_degradation',target_correct=105,regressions=1,improvements=1,p_value=1)
        view=explain(row)
        self.assertIn('本场两边成绩相同',view['reference_note'])
        self.assertIn('型号身份仍待确认',view['identity'])
