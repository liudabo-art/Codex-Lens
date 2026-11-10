const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../relay_auditor/web/app.js');

test('unknown usage never renders as zero', () => {
  assert.equal(ui.formatCount(null), '未知');
  assert.equal(ui.formatCount(0), '0');
});
test('screening consistency never becomes certified model identity', () => {
  assert.equal(ui.identityLabel('baseline_missing'), '缺少匹配基线');
  assert.equal(ui.identityLabel('screening_consistent'), '筛查未见偏离（实验性）');
  assert.equal(ui.identityLabel('no_detected_deviation'), '本次未检出行为差异');
});
test('user interval preserves seconds and rejects invalid values', () => {
  assert.equal(ui.intervalSeconds('2.5', 'minutes'), 150);
  assert.equal(ui.intervalSeconds('30', 'seconds'), 30);
  assert.throws(() => ui.intervalSeconds('0', 'minutes'));
  assert.throws(() => ui.intervalSeconds('NaN', 'minutes'));
});
test('formal identity audit counts both channels', () => {
  assert.equal(ui.estimateRequests('identity_audit', 50), 500);
  assert.equal(ui.estimateRequests('capability_audit', 40), 80);
  assert.equal(ui.estimateRequests('baseline', 12), 12);
});
test('quality and reasoning estimates include all reference calls',()=>{
  assert.equal(ui.estimateRequests('quality_audit',40),80);
  assert.equal(ui.estimateRequests('reasoning',5),10);
  assert.equal(ui.estimateRequests('reasoning',5,true),20);
  assert.equal(ui.estimateRequests('screen',100),3);
  assert.equal(ui.qualityText({accuracy:null}),'未测 / 无有效证据');
});
test('custom names and UI-only model mappings never enter browser exports', () => {
  const result = ui.exportSnapshot({schema_version:1,history:[],display_names:{'relay-1':'PRIVATE-NAME'},
    model_choices:{'relay-1':['gpt-test']},catalog_models:{},catalog_reasoning:{},desktop:true,
    official_presets:[{id:'openai',label:'OpenAI'}],history_reports:[{headline:'shared copy'}]});
  assert.deepEqual(result,{schema_version:1,history:[]});
});
test('official reference summary shows the selected provider and exact model mapping', () => {
  const presets = [{id:'openai',label:'OpenAI'}];
  const target = {model:'gpt5.6sol',reference_preset:'openai',reference_model:'gpt-5.6-sol'};
  assert.equal(ui.referenceSummary({...target,assessment_plan:{reference_state:'reference_matched'}},presets),
    '已匹配 OpenAI · 中转 gpt5.6sol ↔ 官方 gpt-5.6-sol');
  assert.match(ui.referenceSummary({...target,assessment_plan:{reference_state:'reference_pending'}},presets),/Key 待首次检测验证/);
  assert.match(ui.referenceSummary({...target,assessment_plan:{reference_state:'reference_mismatch'}},presets),/本轮只测能力/);
  assert.match(ui.referenceSummary({...target,reference_preset:null,assessment_plan:{reference_state:'reference_matched'}},presets),/旧版同型号官方参考/);
});
test('new targets do not inherit labels from history or jobs for a different target ID', () => {
  const data = {targets:[{source_alias:'relay-1',target_id:'target-new'}],display_names:{'relay-1':'新检测目标'}};
  assert.equal(ui.targetLabel(data,{source_alias:'relay-1',target_id:'target-new'}),'新检测目标');
  assert.equal(ui.targetLabel(data,{source_alias:'relay-1',target_id:'target-old'}),'relay-1（已删除）');
  assert.equal(ui.targetLabel(data,{source_alias:'relay-1'}),'relay-1');
  assert.equal(ui.targetLabel(data,{source_alias:'relay-1',source_kind:'official_api'}),'官方直连');
});

test('follow-up reports show the original screen and new paired scores for the same target', () => {
  const screen = {job_id:'screen-1', target_id:'target-1', paired_result:{valid_pairs:10,target_correct:6,reference_correct:10}};
  const review = {review_of:'screen-1', target_id:'target-1', paired_result:{valid_pairs:40,target_correct:31,reference_correct:37}};
  assert.equal(ui.pairedReviewSummary(review, [screen]), '初筛 10 对，中转 6/10、官方 10/10。新题复核 40 对，中转 31/40、官方 37/40。');
  assert.equal(ui.pairedReviewSummary({...review,paired_result:{valid_pairs:0}}, [screen]),
    '初筛 10 对，中转 6/10、官方 10/10。新题复核暂未获得可比较的答题结果。');
  assert.equal(ui.pairedReviewSummary(review, [{...screen,target_id:'other'}]), '新题复核 40 对，中转 31/40、官方 37/40。');
  assert.equal(ui.pairedReviewSummary(screen, []), '');
});

test('target selection survives a reorder and falls back when the selected target is removed', () => {
  const first = {target_id:'first'};
  const second = {target_id:'second'};
  assert.equal(ui.selectedTarget([first, second], 'second'), second);
  assert.equal(ui.selectedTarget([second, first], 'first'), first);
  assert.equal(ui.selectedTarget([first], 'second'), first);
  assert.equal(ui.selectedTarget([], 'second'), null);
});

test('report view preserves the shared verdict and observed difference without recomputing a verdict', () => {
  const brief = {headline:'证据不足',observed:'中转 7/10，官方 9/10。低 20 个百分点。',
    coverage:['可比较 10/10 对'],next_step:'用新题复核',format_notes:['格式恢复 1 次'],task_details:['分支追踪 2/3']};
  const view = ui.reportView(brief);
  for (const key of Object.keys(brief)) assert.deepEqual(view[key], brief[key]);
  assert.equal(ui.reportView(null).headline, '等待检测');
});

test('history entry retains one snapshot pair when polling inserts or reorders rows', () => {
  const data = {history:[{job_id:'first'},{job_id:'second'}],history_reports:[{headline:'first'},{headline:'second'}]};
  const entry = ui.historyEntry(data, 1);
  data.history = [{job_id:'new'}, ...data.history];
  data.history_reports = [{headline:'new'}, ...data.history_reports];
  assert.equal(entry.record.job_id, 'second');
  assert.equal(entry.report.headline, 'second');
  assert.equal(ui.historyEntry(data, 99), null);
});

test('request preview separates target and official calls and accepts older estimates', () => {
  assert.equal(ui.requestSummary({required_requests:20,target_requests:10,reference_requests:10}), '20 次请求（目标 10 次、官方参考 10 次）');
  assert.equal(ui.requestSummary({required_requests:10}), '10 次请求');
  assert.match(ui.requestSummary({required_requests:10,max_retry_requests:20}), /最多额外 20 次/);
});

test('only new assessment interruptions prompt the user', () => {
  const old = {mode:'assessment', job_id:'old', failure_source:'relay', status:'unavailable'};
  const failed = {...old, job_id:'new'};
  const cancelled = {...old, job_id:'cancelled', status:'cancelled'};
  const data = {history:[failed,old,cancelled], history_reports:[{headline:'检测中止'},{headline:'旧结果'},{}]};
  assert.deepEqual(ui.newAssessmentFailures(null, data), []);
  assert.deepEqual(ui.newAssessmentFailures({history:[old]}, data), [{headline:'检测中止'}]);
  assert.deepEqual(ui.newAssessmentFailures(data, data), []);
  assert.match(ui.assessmentProgress({retry:{source_kind:'reference',retry_question:3,retry_attempt:2}}), /官方参考.*第 3 题.*第 2 次/);
});
