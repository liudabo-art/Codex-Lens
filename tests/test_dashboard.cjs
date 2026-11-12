const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../relay_auditor/web/app.js');

test('clear-all removes cached cards outside the visible history after a refresh failure', () => {
  const state={history:[{record_id:'visible'}],history_reports:[{}],targets:[{source_alias:'relay-1',last_result:{record_id:'older'}}],report_cards:{'relay-1':{headline:'old'}}};
  const next=ui.pruneDeletedHistory(state,{all:true},0);
  assert.deepEqual(next.report_cards,{});
  assert.equal(next.targets[0].last_result,null);
  assert.equal(next.history_count,0);
});

test('deleting a screen retains review marks and clears the cached review eligibility', () => {
  const screen={record_id:'a',job_id:'screen'},review={record_id:'b',review_of:'screen',capability_correct:35};
  const state={history:[review,screen],history_reports:[{coverage:[]},{}],targets:[{source_alias:'relay-1',last_result:review,review_job_id:'screen',review_available:true}],report_cards:{'relay-1':{coverage:[]}}};
  const next=ui.pruneDeletedHistory(state,{record_ids:['a']},1);
  assert.equal(next.targets[0].review_available,false);
  assert.equal(next.history[0].capability_correct,35);
  assert.equal(next.history[0].review_source_deleted,true);
  assert.match(next.report_cards['relay-1'].coverage.join(' '),/初筛记录已删除/);
});

test('history selection follows stable record IDs across filtering and polling', () => {
  const a = {record_id:'a',mode:'assessment'}, b = {record_id:'b',mode:'capability_exam',task_count:120};
  assert.deepEqual(ui.historySelection({history:[b,a]}, new Set(['a','b','deleted']), 'all'), ['a','b']);
  assert.deepEqual(ui.historySelection({history:[b,a]}, new Set(['a','b']), 'exam120'), ['b']);
  assert.deepEqual(ui.historySelection({history:[b]}, new Set(['a']), 'all'), []);
});

test('deleting records does not announce an older failure filling the history window', () => {
  const record = {mode:'capability_exam',status:'unavailable',job_id:'older-failure'};
  const report = {headline:'未交卷'};
  assert.deepEqual(ui.newAssessmentFailures({history:[]}, {history:[record],history_reports:[report]}, true), []);
});

test('deleted review source is identified explicitly rather than inferred from visible window', () => {
  const review={review_of:'prior',review_source_deleted:true,paired_result:{valid_pairs:40,target_correct:35,reference_correct:39}};
  assert.match(ui.pairedReviewSummary(review, []), /初筛记录已删除.*新题复核/);
});

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

test('exam preview binds start to a fresh plan and shows full budget and shortfalls', () => {
  const estimate = {status:'ok', exam_plan_id:'plan-id', model:'gpt-test', reasoning_effort:'high',
    reference_model:'gpt-test-official', reference_reasoning_effort:'medium', max_output_tokens:8192,
    reference_max_output_tokens:4096, required_requests:240,
    target_requests:120, reference_requests:120, max_retry_requests:48, max_requests:288,
    estimated_tokens:900000, minimum_request_limit:298, minimum_token_limit:915000};
  const budget = {request_limit:100, token_limit:100000};
  const approved = ui.examEstimateView(estimate, budget);
  assert.equal(approved.planId, 'plan-id');
  assert.match(approved.settings, /中转 gpt-test（推理 high，输出上限 8,192 token）.*官方 gpt-test-official（推理 medium，输出上限 4,096 token）/);
  assert.match(approved.cost, /基础 240 次.*中转 120 次.*官方参考 120 次.*最多重试 48 次.*最多 288 次.*900,000 token.*费用未知/);
  const blocked = ui.examEstimateView({...estimate, status:'budget_exhausted'}, budget);
  assert.equal(blocked.planId, null);
  assert.deepEqual(blocked.budget, {requests:298, tokens:915000});
  assert.match(blocked.shortfall, /还差 198 次请求.*815,000 token/);
  assert.equal(ui.examEstimateView({...estimate, exam_plan_id:null}, budget).planId, null);
});

test('exam history distinguishes the two papers without changing report indices', () => {
  const routine = {mode:'assessment', task_count:10};
  const standard = {mode:'capability_exam', task_count:120, sample_count:240};
  const extended = {mode:'capability_exam', task_count:180};
  assert.equal(ui.runLabel(standard), '能力考试 · 标准卷（120 题）');
  assert.equal(ui.runLabel(extended), '能力考试 · 加长卷（180 题）');
  assert.equal(ui.historyMatches(standard, 'exam180'), false);
  assert.equal(ui.historyMatches(extended, 'exam180'), true);
  assert.equal(ui.historyMatches(routine, 'routine'), true);
  assert.equal(ui.historyMatches(standard, 'routine'), false);
});

test('exam shows both sides of completion independently of attempts and alerts on interruption', () => {
  const progress = {completed:18,total:240,exam_progress:[
    {source_kind:'relay',completed:8,sample_count:120},{source_kind:'reference',completed:7,sample_count:120}],
    retry:{source_kind:'reference',retry_question:8,retry_attempt:1}};
  assert.match(ui.assessmentProgress(progress), /中转 8\/120 题.*官方参考 7\/120 题.*官方参考正在重试第 8 题/);
  const failure = {mode:'capability_exam',status:'unavailable',failure_source:'reference',job_id:'exam-id'};
  const cancelled = {...failure, status:'cancelled', job_id:'cancelled-exam'};
  const brief = {headline:'未交卷',diagnostics:['官方参考第 8 题失败'],next_step:'检查连接'};
  const data = {history:[failure,cancelled],history_reports:[brief,brief]};
  assert.deepEqual(ui.newAssessmentFailures({history:[]}, data), [brief]);
  assert.deepEqual(ui.newAssessmentFailures(data, data), []);
});
