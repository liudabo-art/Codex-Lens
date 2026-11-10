(function () {
  'use strict';
  const identityNames = {
    baseline_missing: '缺少匹配基线', baseline_stale: '参考基线已过期',
    screening_consistent: '筛查未见偏离（实验性）', screening_deviation: '指纹偏离，需复核',
    invalid_probe: '指纹响应不完整或格式不符', insufficient_data: '样本不足，无法判断',
    insufficient_resolution: '检验分辨率不足，无法判断', behavior_deviation: '本次服务行为显著偏离参考',
    no_detected_deviation: '本次未检出行为差异'
  };
  const names = {ok:'已完成', cancelled:'已取消后续请求', budget_exhausted:'预算不足，已暂停',
    unavailable:'暂不可用', disabled:'检测已关闭', idle:'等待下一轮', waiting_for_activity:'等待使用活动',
    running:'检测中', reference_required:'需要独立官方 API 对照', authentication_failed:'认证失败',
    rate_limited:'触发限流', unsupported_parameters:'参数不支持', network_error:'网络请求失败',
    invalid_response:'响应格式不支持', no_data:'未观察', observed_answers_correct:'本轮有效题均答对',
    screening_failure:'本轮存在答错项，待复测', insufficient_data:'样本不足，无法判断',
    incomplete_comparison:'存在缺失，比较不完整', degraded:'配对测试显示能力下降',
    inconclusive:'存在下降线索，证据不足', no_detected_degradation:'本次未检出能力下降',
    screen:'日常筛查', baseline:'官方指纹登记', identity_audit:'正式行为审计', capability_audit:'旧版配对能力审计',
    quality:'基础质量体检',quality_audit:'增强配对评测',context:'长上下文专项',reasoning:'推理档位比较',
    credential_required:'请补充专用 Key',queued:'排队中',finished:'已完成',cancelling:'正在停止',
    not_comparable:'条件不匹配，无法比较',historical_decline_signal:'历史下降线索（需复核）',
    basic_observation:'基础观察',matched_official_comparison:'同期官方对照',historical_reference:'历史参考',legacy_unverified:'旧版未验证',
    no_reference:'无匹配参考', assessment:'模型检测', identity_uncalibrated:'已取样，待校准',
    not_tested:'暂无型号对照', official_direct:'官方直连'};
  const wireNames={responses:'OpenAI Responses',chat:'Chat Completions',deepseek:'DeepSeek Chat',anthropic:'Anthropic Messages',gemini:'Gemini'};
  const familyNames={gpt:'GPT / Codex',deepseek:'DeepSeek',claude:'Claude',gemini:'Gemini',qwen:'Qwen',glm:'GLM',kimi:'Kimi',minimax:'MiniMax',grok:'Grok',mistral:'Mistral',llama:'Llama'};
  function formatCount(value) { return value == null || !Number.isFinite(value) ? '未知' : value.toLocaleString('zh-CN'); }
  function identityLabel(value) { return identityNames[value] || '尚无可比较结果'; }
  function intervalSeconds(value, unit) {
    const n = Number(value) * (unit === 'hours' ? 3600 : unit === 'minutes' ? 60 : 1);
    if (!Number.isFinite(n) || n <= 0) throw new Error('invalid_interval');
    return n;
  }
  function estimateRequests(mode, samples, hasReference=false) { return mode==='screen' ? 3 : samples * (mode === 'identity_audit' ? 10 : ['quality_audit','capability_audit'].includes(mode) ? 2 : mode==='reasoning' ? (hasReference ? 4 : 2) : 1); }
  function percent(value) { return Number.isFinite(value) ? (value*100).toFixed(1)+'%' : '无法判断'; }
  function qualityText(quality) { return !quality || quality.accuracy==null ? '未测 / 无有效证据' : percent(quality.accuracy)+(quality.interval ? `（${quality.interval.map(percent).join(' – ')}）` : ''); }
  const referenceErrors = {
    authentication_failed:'官方 Key 未通过认证，请检查 Key、权限及所选站点。',
    network_error:'暂时无法连接所选官方站点，请检查网络后重试。',
    rate_limited:'官方模型目录请求被限流，请稍后重试。',
    invalid_response:'官方模型目录返回了无法识别的结果，请稍后重试。',
    redirect_blocked:'官方模型目录请求发生重定向，已停止查询。',
    invalid_reference_preset:'请选择列表里的官方供应商。',
    reference_provider_mismatch:'所选官方供应商与中转声明的模型家族不匹配。',
    reference_model_mismatch:'在所选官方入口未找到同型号，请检查中转声明及官方 Key 权限。',
    reference_model_unavailable:'该官方 Key 或站点当前无法使用这个型号，请检查型号权限。',
    reference_model_retired:'官方已停用此版本，旧型号 ID 现指向另一版本。可继续单测中转。',
    reference_settings_mismatch:'两边的推理或请求设置不可比，请调整检测设置。',
    reference_changed:'目标设置已变化，请重新打开对照面板后再匹配。',
    target_not_found:'检测目标已移除，请刷新目标列表。',
    busy:'请先停止本轮检测，再保存官方参考。',
    unsupported_parameters:'两边的推理或请求设置不可比，请调整检测设置。',
    http_error:'官方模型目录暂时无法查询，请稍后重试。',
    models_unavailable:'官方模型目录暂时无法查询，请稍后重试。'
  };
  function presetLabel(presets, id) { return presets.find(preset => preset.id === id)?.label || '官方'; }
  function referenceSummary(target, presets) {
    const plan = target.assessment_plan || {};
    const model = target.reference_model;
    const provider = presetLabel(presets, target.reference_preset);
    switch (plan.reference_state) {
      case 'reference_matched':
      case 'reference_pending': {
        if (!target.reference_preset) return '已匹配旧版同型号官方参考' + (model ? ' · ' + model : '');
        const mapping = target.model !== model ? '中转 ' + target.model + ' ↔ 官方 ' + model : model;
        const pending = plan.reference_state === 'reference_pending' ? ' · Key 待首次检测验证' : '';
        return '已匹配 ' + provider + (model ? ' · ' + mapping : '') + pending;
      }
      case 'official_direct': return '官方直连能力测试';
      case 'reference_missing': return '只测模型能力';
      case 'reference_key_required': return '请补充 ' + provider + ' Key · 本轮只测能力';
      case 'reference_mismatch': return (referenceErrors[target.reference_error] || '参考型号或请求设置不匹配') + ' · 本轮只测能力';
      case 'reference_unavailable': return (referenceErrors[target.reference_error] || '官方参考暂不可用') + ' · 本轮只测能力';
      default: return '正在读取设置';
    }
  }
  function targetLabel(data, item) {
    if (item.source_kind === 'official_api') return '官方直连';
    if (!item.target_id) return item.source_alias;
    const target = data.targets.find(target => target.target_id === item.target_id);
    return target ? data.display_names[target.source_alias] || target.source_alias : item.source_alias + '（已删除）';
  }
  function pairedReviewSummary(result, history) {
    if (!result?.review_of) return '';
    const source = history.find(row => row.job_id === result.review_of && row.target_id === result.target_id);
    const scores = pair => `${pair.valid_pairs} 对，中转 ${pair.target_correct}/${pair.valid_pairs}、官方 ${pair.reference_correct}/${pair.valid_pairs}。`;
    const initial = source?.paired_result?.valid_pairs ? '初筛 ' + scores(source.paired_result) : '';
    const review = result.paired_result;
    return initial + (review?.valid_pairs ? '新题复核 ' + scores(review) : '新题复核暂未获得可比较的答题结果。');
  }
  function selectedTarget(targets, targetId) {
    return targets.find(target => target.target_id === targetId) || targets[0] || null;
  }
  function reportView(brief) {
    const value = brief || {};
    const view = {};
    for (const key of ['headline','observed','comparison','reference_note','identity','evaluated_at','next_step','limitations'])
      view[key] = typeof value[key] === 'string' ? value[key] : '';
    view.headline ||= '等待检测';
    for (const key of ['coverage','diagnostics','format_notes','task_summary','task_details','details'])
      view[key] = Array.isArray(value[key]) ? value[key].filter(item => typeof item === 'string') : [];
    view.score_tiles = Array.isArray(value.score_tiles) ? value.score_tiles.filter(item =>
      typeof item?.label === 'string' && typeof item?.score === 'string') : [];
    return view;
  }
  function historyEntry(data, index) {
    const record = data.history?.[index], report = data.history_reports?.[index];
    return record && report ? {record, report} : null;
  }
  function requestSummary(plan) {
    const total = formatCount(plan.required_requests) + ' 次请求';
    const bySide = Number.isSafeInteger(plan.target_requests) && Number.isSafeInteger(plan.reference_requests)
      ? total + `（目标 ${formatCount(plan.target_requests)} 次、官方参考 ${formatCount(plan.reference_requests)} 次）` : total;
    return plan.max_retry_requests > 0 ? bySide + `，断连时最多额外 ${formatCount(plan.max_retry_requests)} 次，计入预算` : bySide;
  }
  function assessmentProgress(progress) {
    const retry = progress?.retry;
    if (retry) {
      const side = {reference:'官方参考', official_api:'官方直连', relay:'中转'}[retry.source_kind] || '目标';
      return `${side}正在重试第 ${retry.retry_question} 题（第 ${retry.retry_attempt} 次重试）`;
    }
    return `已尝试 ${progress?.completed || 0}/${progress?.total || 0} 次请求`;
  }
  function newAssessmentFailures(previous, data) {
    if (!previous) return [];
    const seen = new Set((previous.history || []).map(row => row.job_id));
    return (data.history || []).flatMap((row, index) => {
      const brief = data.history_reports?.[index];
      return brief && row.mode === 'assessment' && row.failure_source && row.job_id && !seen.has(row.job_id)
        && ['unavailable','budget_exhausted'].includes(row.status) ? [brief] : [];
    });
  }
  function exportSnapshot(data) {
    const {display_names, model_choices, catalog_models, catalog_reasoning, desktop, vault_available, settings_status, report_cards, history_reports, official_presets, ...snapshot} = data;
    return snapshot;
  }
  const exported = {formatCount, identityLabel, intervalSeconds, estimateRequests, exportSnapshot, qualityText, referenceSummary, targetLabel, pairedReviewSummary, selectedTarget, reportView, historyEntry, requestSummary, assessmentProgress, newAssessmentFailures};
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  function renderReport(container, brief) {
    const view = reportView(brief);
    const signature = JSON.stringify(view);
    if (container.dataset.report === signature) return;
    container.dataset.report = signature;
    // Preserve disclosure state across polling; every dynamic value is text.
    const expanded = container.querySelector('details')?.open || false;
    container.replaceChildren();
    function text(parent, tag, value, cls='') {
      if (!value) return;
      const node = document.createElement(tag); node.className = cls; node.textContent = value; parent.append(node);
      return node;
    }
    const heading = document.createElement('div'); heading.className = 'report-heading'; container.append(heading);
    const lead = document.createElement('div'); lead.className = 'report-copy'; heading.append(lead);
    text(lead, 'p', '实验性 · ' + (view.evaluated_at ? new Date(view.evaluated_at).toLocaleString() : '尚无检测时间'), 'report-time muted');
    text(lead, 'h3', view.headline, 'verdict');
    text(lead, 'p', view.observed, 'report-observed');
    if (view.score_tiles.length) {
      const tiles = document.createElement('div'); tiles.className = 'paired-scores'; heading.append(tiles);
      view.score_tiles.forEach((tile, index) => {
        const tileNode = document.createElement('div'); tileNode.className = index ? 'paired-score' : 'paired-score relay-score';
        text(tileNode, 'span', tile.label, 'score-label'); text(tileNode, 'strong', tile.score, 'score-value'); tiles.append(tileNode);
      });
    }
    text(container, 'p', view.reference_note || view.comparison, 'report-comparison-summary');
    view.coverage.forEach(line => text(container, 'p', line, 'report-coverage'));
    if (view.diagnostics.length) {
      const list = document.createElement('ul'); list.className = 'diagnostics'; container.append(list);
      view.diagnostics.forEach(line => text(list, 'li', line));
    }
    view.format_notes.forEach(line => text(container, 'p', line, 'format-note muted'));
    text(container, 'p', view.next_step, 'report-next-step');
    text(container, 'p', view.limitations, 'report-limits muted');
    if (view.task_summary.length) {
      text(container, 'h4', '能力分项与专项结果');
      const list = document.createElement('ul'); list.className = 'report-tasks'; container.append(list);
      view.task_summary.forEach(line => text(list, 'li', line));
    }
    if (brief) {
      const details = document.createElement('details'); details.className = 'professional'; details.open = expanded;
      text(details, 'summary', '专业详情'); text(details, 'p', view.identity);
      [...view.details, ...view.task_details].forEach(line => text(details, 'p', line)); container.append(details);
    }
  }
  function openHistoryReport(entry) {
    $('historyReportTitle').textContent = '历史报告 · ' + (entry.record.source_alias || '历史目标') + ' · ' + (entry.record.model || '');
    renderReport($('historyReportContent'), entry.report);
    $('historyReportDialog').showModal();
  }
  const label = value => names[value] || identityNames[value] || '状态未知';
  const runLabel = result => result.review_of ? '新题复核' : label(result.mode);
  let state = null, pollRequest = null, pollTimer = null, noticeId = null, audit = null, catalogSignature = '', desktopNotifications = false;
  let referenceTargetId = null, deleteTargetId = null, selectedTargetId = null;
  const targetPicker = $('targetPicker'), targetPickerField = $('targetPickerField');
  function message(text, error) { $('message').textContent = text; $('message').classList.toggle('error', Boolean(error)); }
  async function post(route, data) {
    const response = await fetch(route, {method:'POST', headers:{'Content-Type':'application/json','X-Relay-Request':'1'}, body:JSON.stringify(data), cache:'no-store'});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || 'request_failed');
    return result;
  }
  const errors = {catalog_not_found:'未在常见位置找到配置，请点击“手动选择配置文件”。', unsupported_schema:'这个配置版本暂不支持，未导入。',
    source_unavailable:'文件不可读，请确认所选配置文件。', dialog_busy:'已有文件选择窗口，请先完成或取消。',
    models_unavailable:'中转不支持模型列表查询，请使用导入配置中的模型。', authentication_failed:'专用 Key 未通过认证，请检查。',
    network_error:'无法连接中转，请检查地址和网络。', invalid_response:'中转返回的模型列表格式不支持。',
    redirect_blocked:'模型列表请求发生重定向，已阻止。',rate_limited:'请求被限流，请降低频率后重试。',http_error:'供应商返回服务错误，请稍后重试。',remote_error:'供应商返回错误或拦截了响应。',response_too_large:'响应超出本地大小限制，已停止读取。',credential_required:'请先在目标卡片补充专用 Key。',
    vault_unavailable:'系统凭据库不可用。取消保存 Key 后可以只在本次运行使用。',profiles_unavailable:'私人配置不可读，已停止写入以保护原文件。',
    reference_required:'此模式需要独立官方 API Key，请在目标卡片补充。',queue_full:'队列已满，请等待或取消部分任务。',
    credential_too_large_for_vault:'此 Key 超过系统凭据库限制，可取消保存 Key 后使用。',unsupported_parameters:'供应商不接受当前参数；请调整协议或推理档位后重试。',
    busy:'请等待当前检测结束，再保存目标设置。',invalid_model:'请先选择检测模型。',invalid_endpoint:'请检查 API 地址。',
    invalid_credential:'目标 Key 格式有误，请重新粘贴后重试。',
    reference_provider_mismatch:referenceErrors.reference_provider_mismatch,
    official_direct:'当前目标为官方直连，可以直接测试能力。',
    budget_exhausted:'本轮预估超过剩余预算。请调整下方每日预算或减少样本。',
    assessment_changed:'检测设置已变化，请查看更新后的请求量再开始。'};
  async function action(route, data, success) {
    try { const result = await post(route, data); message(result.cancelled ? '已取消选择，配置保持不变。' : success || '已更新'); await poll(); return result; }
    catch (error) { message(errors[error.message] || '操作未完成。请检查输入、目标状态及是否已有检测正在运行。', true); return null; }
  }
  async function busy(button, work) {
    if (button.dataset.pending) return;
    button.dataset.pending = '1';
    const text = button.textContent; button.disabled = true; button.textContent = '正在处理…';
    try { return await work(); } finally { delete button.dataset.pending; button.disabled = false; button.textContent = text; }
  }
  function setModels(select, models, selected, placeholder='请选择模型') {
    const all = [...new Set([...(selected ? [selected] : []), ...models])]; select.replaceChildren();
    const empty = document.createElement('option'); empty.value = ''; empty.textContent = placeholder; select.append(empty);
    all.forEach(id => { const option = document.createElement('option'); option.value = id; option.textContent = id; select.append(option); });
    select.value = selected || '';
  }
  function reasoningSelect(value) {
    const select = document.createElement('select');
    ['', 'none','minimal','low','medium','high','xhigh','max'].forEach(effort => {
      const option = document.createElement('option'); option.value = effort; option.textContent = effort || '模型默认'; select.append(option);
    }); select.value = value || ''; return select;
  }
  function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.append(td); }
  function sameTarget(item, target) {
    return item?.target_id ? item.target_id === target.target_id : item?.source_alias === target.source_alias;
  }
  function activeJob(target) {
    return (state.jobs || []).find(job => sameTarget(job, target) && ['queued','running','cancelling'].includes(job.state));
  }
  function runningTarget(target) {
    return ['running','cancelling'].includes(activeJob(target)?.state)
      || Boolean(state.busy && sameTarget(state.progress, target));
  }
  function showTarget(targetId) {
    const target = selectedTarget(state.targets, targetId);
    selectedTargetId = target?.target_id ?? null;
    const card = target && $('target-' + target.source_alias);
    const parent = card?.querySelector('.start-row') || $('targetPickerHome');
    const pickerFocused = document.activeElement === targetPicker;
    const moved = targetPickerField.parentElement !== parent;
    if (moved) parent.prepend(targetPickerField);
    targetPickerField.hidden = !card;
    if (targetPicker.value !== selectedTargetId) targetPicker.value = selectedTargetId || '';
    $('targets').querySelectorAll('.target').forEach(item => { item.hidden = item !== card; });
    if (pickerFocused && moved && card) targetPicker.focus({preventScroll:true});
    return card;
  }
  function renderTargetPicker(data) {
    const options = data.targets.map(target => [target.target_id, data.display_names[target.source_alias] || target.source_alias]);
    const signature = JSON.stringify(options);
    if (targetPicker.dataset.signature !== signature) {
      targetPicker.dataset.signature = signature;
      targetPicker.replaceChildren(...options.map(([id, name]) => new Option(name, id)));
    }
    showTarget(selectedTargetId);
  }
  async function showAddedTarget(alias) {
    if (!state.targets.some(target => target.source_alias === alias)) await refreshState();
    const target = state.targets.find(item => item.source_alias === alias);
    if (!target) return;
    const card = showTarget(target.target_id);
    card?.scrollIntoView({block:'start'});
    card?.querySelector('.start-assessment').focus({preventScroll:true});
  }
  targetPicker.addEventListener('change', () => showTarget(targetPicker.value));
  function targetCard(target) {
    const card = document.createElement('article'); card.className = 'target'; card.id = 'target-' + target.source_alias;
    card.dataset.targetId = target.target_id;
    card.innerHTML = `
      <div class="target-toolbar">
        <div class="start-row">
          <div class="model-field"></div>
          <div class="match-field"><span class="toolbar-label">官方匹配</span><span class="match-hint"></span></div>
          <p class="plan-hint muted" role="status"></p><button class="primary start-assessment">开始检测</button>
        </div>
        <div class="target-top">
          <div class="target-context"><div class="target-name"></div><div class="target-model"></div></div>
          <div class="target-top-actions"><span class="pill"></span><button class="open-reference">补充官方参考</button>
            <button class="cancel-target" hidden>停止本轮检测</button>
            <details class="target-menu"><summary aria-label="目标操作">⋯</summary><button type="button" class="delete-target">删除检测目标</button></details>
          </div>
        </div>
        <p class="start-feedback" role="status" hidden></p>
        <p class="target-action-status dialog-feedback" role="status"></p>
      </div>
      <section class="report-summary" aria-label="检测结论">
        <div class="shared-report"></div>
        <p class="review-context"></p>
        <div class="actions review-actions" hidden><button type="button" class="review-assessment">用新题复核</button><span class="muted">先查看额外请求量，再决定是否开始。</span></div>
      </section>` +
      '<details class="credentialSettings"><summary>管理目标 Key</summary><form class="credentialForm" autocomplete="off"><div class="form-grid"><label>目标 API Key<input name="api_key" type="password" autocomplete="off" required></label></div><label class="checkbox"><input name="save_credentials" type="checkbox">存入系统凭据库</label><button type="submit">保存目标 Key</button><p class="muted">锁定时，填入 Key 后可直接点「开始检测」。勾选保存后，下次启动会自动解锁。</p></form></details>' +
      '<details class="target-advanced"><summary>检测设置与专项测试</summary><div class="settings-fields"></div><div class="controls"><label class="checkbox"><input class="enabled" type="checkbox">开启周期检测</label><div class="control-pair"><label>检测间隔<input class="interval" type="number" min="0.001" step="any" value="15"></label><label>单位<select class="unit"><option value="minutes">分钟</option><option value="seconds">秒</option><option value="hours">小时</option></select></label></div><label class="checkbox"><input class="activeOnly" type="checkbox" checked>仅使用时检测</label><button class="saveControl">保存设置</button></div>' +
      '<div class="actions"><button data-mode="assessment">增加检测样本</button><button data-mode="context">长上下文专项</button><button data-mode="reasoning">推理档位比较</button><button data-mode="baseline">登记旧版指纹</button><button data-mode="identity_audit">实验行为审计</button><button class="activeNow">标记正在使用</button></div></details>';
    card.querySelector('.target-name').textContent = state.display_names[target.source_alias] || '未命名测试';
    card.querySelector('.target-model').textContent = target.model;
    const settings = document.createElement('div'); settings.className = 'form-grid target-settings';
    const nameLabel = document.createElement('label'); nameLabel.textContent = '测试名称';
    const nameInput = document.createElement('input'); nameInput.className = 'displayName'; nameInput.maxLength = 60; nameInput.value = state.display_names[target.source_alias] || '未命名测试'; nameLabel.append(nameInput);
    const modelLabel = document.createElement('label'); modelLabel.textContent = '检测模型';
    const modelSelect = document.createElement('select'); modelSelect.className = 'modelChoice'; setModels(modelSelect,state.model_choices[target.source_alias] || [],target.model); modelLabel.append(modelSelect);
    const effortLabel = document.createElement('label'); effortLabel.textContent = '推理档位'; const effort = reasoningSelect(target.reasoning_effort); effort.className = 'effort'; effortLabel.append(effort);
    const wireLabel = document.createElement('label'); wireLabel.textContent = '请求协议';
    const wire = document.createElement('select'); wire.className = 'wireChoice';
    Object.entries(wireNames).forEach(([value, title]) => wire.add(new Option(title, value)));
    wire.value = target.wire_api; wireLabel.append(wire);
    const buttons = document.createElement('div'); buttons.className = 'actions';
    const refresh = document.createElement('button'); refresh.textContent = '刷新模型列表';
    refresh.addEventListener('click', () => busy(refresh, async () => {
      const result = await action('models',{source_alias:target.source_alias},'模型列表已读取。');
      if (result) setModels(modelSelect,result.models,modelSelect.value);
    }));
    const save = document.createElement('button'); save.textContent = '保存名称与模型参数';
    save.addEventListener('click', () => busy(save, async () => {
      const result = await action('target_options',options(),'已保存检测设置。');
      if (result) { card.querySelector('.target-name').textContent = nameInput.value; card.querySelector('.target-model').textContent = modelSelect.value; delete card.dataset.dirty; }
    }));
    function options() { return {source_alias:target.source_alias,display_name:nameInput.value,model:modelSelect.value,reasoning_effort:effort.value,wire_api:wire.value}; }
    buttons.append(refresh,save); settings.append(nameLabel,effortLabel,wireLabel,buttons);
    card.querySelector('.settings-fields').append(settings);
    card.querySelector('.model-field').append(modelLabel);
    const credentialDetails = card.querySelector('.credentialSettings');
    const credentialForm = card.querySelector('.credentialForm');
    let savingKey = null;
    function saveTargetKey() {
      if (!savingKey) {
        const fields = credentialForm.elements;
        savingKey = post('credentials', {source_alias:target.source_alias, api_key:fields.api_key.value.trim(),
          save_credentials:!fields.save_credentials.disabled && fields.save_credentials.checked}).then(() => {
          credentialForm.reset();
        }).finally(() => { savingKey = null; });
      }
      return savingKey;
    }
    const referenceButton = card.querySelector('.open-reference');
    referenceButton.addEventListener('click', () => busy(referenceButton, async () => {
      if (card.dataset.dirty) {
        if (!await action('target_options', options(), '已应用当前模型、名称与推理档位。')) return;
        delete card.dataset.dirty;
        await refreshState();
        if (state.targets.find(item => item.target_id === target.target_id)?.model !== modelSelect.value) {
          return message('暂时无法确认已保存的型号，请刷新后再补充官方参考。', true);
        }
      }
      openReference(target.target_id);
    }));
    card.querySelector('.delete-target').addEventListener('click', () => openDelete(target, card));
    card.querySelector('.cancel-target').addEventListener('click', event => busy(event.currentTarget, async () => {
      const job = activeJob(target);
      if (job || runningTarget(target)) await action('cancel', job ? {job_id:job.job_id} : {}, '已请求停止后续检测。');
    }));
    const start = card.querySelector('.start-assessment');
    start.addEventListener('click', () => busy(start, async () => {
      const feedback = card.querySelector('.start-feedback');
      feedback.hidden = false;
      feedback.textContent = '正在检查设置和预算…';
      try {
        const current = state.targets.find(t => t.target_id === target.target_id);
        if (!current) {
          feedback.textContent = '此检测目标已移除，请刷新列表。';
          return;
        }
        if (!current.credential_ready) {
          if (!savingKey && !credentialForm.elements.api_key.value.trim()) {
            credentialDetails.open = true; credentialForm.elements.api_key.focus();
            feedback.textContent = '请填写目标 API Key，再点「开始检测」。';
            return;
          }
          feedback.textContent = '正在解锁目标…';
          await saveTargetKey();
          await refreshState();
        }
        if (card.dataset.dirty) {
          await post('target_options', options());
          delete card.dataset.dirty;
        }
        const plan = await post('estimate', {source_alias:target.source_alias,mode:'assessment'});
        if (plan.status !== 'ok') {
          feedback.textContent = errors[plan.status] || '当前设置暂时无法开始检测。';
          return;
        }
        if (plan.required_requests !== current.assessment_plan.required_requests) {
          feedback.textContent = '模型或参考设置已更新，请查看新的请求量后再次开始。';
          await poll();
          return;
        }
        await post('run', {source_alias:target.source_alias,mode:'assessment',expected_requests:plan.required_requests});
        feedback.textContent = '已提交检测，正在等待结果。';
        await poll();
      } catch (error) {
        feedback.textContent = errors[error.message] || '暂时无法提交检测，请检查本机服务后重试。';
      }
    }));
    credentialForm.addEventListener('submit', event => {
      event.preventDefault();
      busy(credentialForm.querySelector('button[type=submit]'), async () => {
        const feedback = card.querySelector('.start-feedback');
        feedback.hidden = false;
        try {
          await saveTargetKey();
          feedback.textContent = '目标 Key 已更新，可以开始检测。';
          await refreshState();
        } catch (error) {
          feedback.textContent = errors[error.message] || '无法更新目标 Key，请检查本机服务后重试。';
        }
      });
    });
    card.querySelector('.interval').value = target.interval_seconds / 60;
    [nameInput,modelSelect,effort,wire].forEach(input => input.addEventListener('input', () => { card.dataset.dirty = '1'; }));
    card.querySelector('.enabled').addEventListener('change', async event => {
      const result = await action('control', {source_alias:target.source_alias, enabled:event.target.checked}, event.target.checked ? '周期检测已开启，后续按间隔和活跃条件运行。' : '已停止后续检测请求，用量观察继续。');
      if (!result) event.target.checked = !event.target.checked;
    });
    card.querySelector('.saveControl').addEventListener('click', async () => {
      try {
        const result = await action('control', {source_alias:target.source_alias,
          interval_seconds:intervalSeconds(card.querySelector('.interval').value, card.querySelector('.unit').value),
          active_only:card.querySelector('.activeOnly').checked}, '间隔与活跃条件已保存，历史证据保持不变。');
      } catch (_) { message('检测间隔需要是大于零的数字。', true); }
    });
    card.querySelector('.activeNow').addEventListener('click', () => action('active', {source_alias:target.source_alias}, '已标记本渠道正在使用，有效期 30 分钟。'));
    card.querySelector('.review-assessment').addEventListener('click', () => {
      const current = state.targets.find(item => item.target_id === target.target_id);
      if (!current?.review_available || card.dataset.dirty || activeJob(target) || runningTarget(target)) {
        return message('检测设置或结果已变化，请确认当前设置后再检测。', true);
      }
      openAudit(target.source_alias, 'assessment', current.last_result.job_id);
    });
    card.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', async () => {
      if (card.dataset.dirty) {
        const saved = await action('target_options',options(),'已应用当前模型、名称与推理档位。');
        if (!saved) return;
        card.querySelector('.target-name').textContent = nameInput.value; card.querySelector('.target-model').textContent = modelSelect.value;
        delete card.dataset.dirty;
      }
      openAudit(target.source_alias, button.dataset.mode);
    }));
    return card;
  }
  function render(data) {
    const failures = newAssessmentFailures(state, data);
    state = data;
    const u = data.usage, b = data.budget;
    $('probeTokens').textContent = formatCount(u.probe_tokens);
    $('referenceTokens').textContent = formatCount(u.reference_tokens);
    $('probeRequests').textContent = `${formatCount(u.probe_requests)} 次请求 · ${formatCount(u.unknown_usage)} 次消耗未核实`;
    $('referenceRequests').textContent = `${formatCount(u.reference_requests)} 次请求 · 与业务用量分开记账`;
    $('directTokens').textContent = formatCount(u.direct_probe_tokens ?? 0);
    $('directRequests').textContent = formatCount(u.direct_probe_requests ?? 0) + ' 次请求';
    $('requestCount').textContent = `${formatCount(b.requests)} / ${formatCount(b.request_limit)}`;
    $('budgetState').textContent = `估算已用 ${formatCount(b.estimated_tokens)} / ${formatCount(b.token_limit)} token`;
    $('workerState').textContent = data.busy ? '正在运行：' + label(data.running_mode) : '检测默认关闭 · 可手动立即检查';
    const targets = $('targets');
    const targetIds = new Set(data.targets.map(target => target.target_id));
    targets.querySelectorAll('.target').forEach(card => {
      if (!targetIds.has(card.dataset.targetId)) {
        if (card.contains(targetPickerField)) $('targetPickerHome').append(targetPickerField);
        card.remove();
      }
    });
    if (data.targets.length) targets.querySelector('.empty')?.remove();
    else if (!targets.querySelector('.empty')) {
      const empty = document.createElement('p'); empty.className = 'empty';
      empty.textContent = '还没有检测目标。添加地址和专用 API Key，或从配置导入。';
      targets.append(empty);
    }
    data.targets.forEach(target => {
      let card = $('target-' + target.source_alias);
      if (!card) { card = targetCard(target); targets.append(card); }
      const official = target.source_kind === 'official_api';
      const plan = target.assessment_plan || {};
      const job = activeJob(target);
      const running = runningTarget(target);
      const family = familyNames[target.model_family];
      const profile = ['gpt','deepseek','claude','gemini'].includes(target.model_family)
        ? family + ' 测试方案' : (family ? family + ' · ' : '') + '通用能力题';
      card.querySelector('.target-name').textContent = data.display_names[target.source_alias] || '检测目标';
      card.querySelector('.target-model').textContent = (official ? 'DeepSeek 官方直连' : '中转') + ' · ' + target.model + ' · ' + profile;
      card.querySelector('.pill').textContent = target.status === 'disabled' ? '周期检测关闭' : label(target.status);
      card.querySelector('.enabled').checked = target.enabled;
      if (!card.dataset.dirty && !card.contains(document.activeElement)) {
        card.querySelector('.activeOnly').checked = target.active_only;
      }
      const r = target.last_result;
      const brief = data.report_cards?.[target.source_alias];
      renderReport(card.querySelector('.shared-report'), brief);
      card.querySelector('.review-context').textContent = pairedReviewSummary(r, data.history || []);
      card.querySelector('.review-actions').hidden = !target.review_available || !target.credential_ready || Boolean(job || running);
      const presets = data.official_presets || [];
      const matched = plan.reference_state === 'reference_matched' && target.reference_preset && target.reference_model;
      card.querySelector('.match-hint').textContent = matched
        ? presetLabel(presets, target.reference_preset) + ' · ' + target.reference_model
        : referenceSummary(target, presets);
      card.querySelector('.plan-hint').textContent = '预计 ' + requestSummary(plan);
      const referenceButton = card.querySelector('.open-reference');
      referenceButton.hidden = official;
      if (!referenceButton.dataset.pending) referenceButton.textContent = target.reference_preset ? '管理官方参考' : '补充官方参考';
      const start = card.querySelector('.start-assessment');
      if (!start.dataset.pending) {
        start.disabled = Boolean(job || running);
        start.textContent = job || running ? label(job?.state || 'running') : '开始检测';
      }
      const cancel = card.querySelector('.cancel-target');
      cancel.hidden = !job && !running;
      if (!cancel.dataset.pending) cancel.disabled = job?.state === 'cancelling';
      const feedback = card.querySelector('.start-feedback');
      if (job || running) {
        feedback.dataset.running = '1';
        feedback.hidden = false;
        feedback.textContent = running
          ? label(job?.state || 'running') + ' · ' + assessmentProgress(data.progress)
          : label(job.state) + ' · 可以取消';
      } else if (r && (feedback.dataset.running || feedback.textContent.startsWith('已提交'))) {
        delete feedback.dataset.running;
        feedback.textContent = r.failure_source ? brief?.headline || '本轮检测已中止。' : '本轮检测已结束，请查看下方结果。';
      }
      card.querySelectorAll('[data-mode]').forEach(button => {
        button.disabled = !target.credential_ready;
        button.hidden = official && ['baseline','identity_audit'].includes(button.dataset.mode);
      });
      card.querySelector('.enabled').disabled=!target.credential_ready;
      card.querySelector('.credentialForm').elements.api_key.required=!target.credential_ready;
      card.querySelector('.credentialForm').elements.save_credentials.disabled=!data.vault_available;
      if(!target.credential_ready) card.querySelector('.credentialSettings').open=true;
    });
    renderTargetPicker(data);
    $('targetForm').elements.save_credentials.disabled=!data.vault_available;
    if(data.settings_status==='unavailable') $('settingsStatus').textContent='私人配置无法读取；已保留原文件并阻止覆盖，请先处理配置文件。';
    const p=data.progress || {};
    $('jobProgress').textContent=data.busy ? `${label(data.running_mode)} · ${assessmentProgress(p)}` : '当前没有运行中的检测';
    $('cancelCurrent').disabled=!data.busy;
    const recentJobs = (data.jobs || []).slice(-10).reverse();
    const jobSignature = JSON.stringify(recentJobs.map(job => [job, targetLabel(data, job)]));
    if ($('jobRows').dataset.signature !== jobSignature) {
      $('jobRows').dataset.signature = jobSignature;
      $('jobRows').replaceChildren();
      recentJobs.forEach(job=>{
      const row=document.createElement('p'); row.className='actions'; const text=document.createElement('span');
      text.textContent=`${targetLabel(data, job)} · ${job.model} · ${runLabel(job)} · ${label(job.state)}`; row.append(text);
      if(job.state==='queued') { const button=document.createElement('button');button.textContent='取消排队';button.addEventListener('click',()=>action('cancel',{job_id:job.job_id},'已取消排队任务。'));row.append(button); }
      $('jobRows').append(row);
      });
    }
    $('comparisonRows').replaceChildren();
    (data.comparisons || []).forEach(item=>{
      const row=document.createElement('tr'); cell(row,`${targetLabel(data, item)} / ${item.model}`);
      cell(row,`${item.suite_version} / ${item.protocol_id}`);cell(row,qualityText(item.last_result.dimensions.quality)+' · '+label(item.last_result.status));
      cell(row,label(item.trend.status)+(item.trend.accuracy_change!=null ? ` · ${(100*item.trend.accuracy_change).toFixed(1)} 个百分点` : ''));
      cell(row,label(item.last_result.evidence_level));$('comparisonRows').append(row);
    });
    $('supportRows').replaceChildren();
    (data.support || []).forEach(item=>{const row=document.createElement('tr');cell(row,item.model+' / '+item.model_family);
      ['can_connect','basic_evaluation','matched_reference','calibrated'].forEach(k=>cell(row,item[k] ? '是' : k==='calibrated' ? '尚未完成' : '否'));$('supportRows').append(row);});
    const providers = data.catalog && data.catalog.providers || [];
    const signature = JSON.stringify(data.catalog);
    if (signature !== catalogSignature) {
      catalogSignature = signature;
      const container = $('catalogRows'); container.replaceChildren();
      providers.forEach(provider => {
        const row = document.createElement('p'); row.className = 'actions';
        const text = document.createElement('span');
        const kind = {official_login:'官方登录配置', official_api:'官方直连 API', relay:'中转配置', unknown:'来源待确认'}[provider.source_kind] || '来源待确认';
        text.textContent = `${provider.source_alias} · ${kind} · ${provider.model || '模型未指定'}${provider.current_selected ? ' · 当前配置选中' : ''}`;
        row.append(text);
        if (provider.source_kind === 'relay' && provider.can_detect) {
          row.classList.add('provider-row');
          const nameInput = document.createElement('input'); nameInput.placeholder = '填写测试名称'; nameInput.maxLength = 60; nameInput.setAttribute('aria-label','导入后的测试名称');
          const model = document.createElement('select'); model.setAttribute('aria-label','导入模型'); setModels(model, data.catalog_models[provider.source_alias] || [],provider.model);
          const effort = reasoningSelect(data.catalog_reasoning[provider.source_alias]); effort.setAttribute('aria-label','导入推理档位');
          const remember = document.createElement('input'); remember.type = 'checkbox';
          const rememberLabel = document.createElement('label'); rememberLabel.className = 'checkbox';
          rememberLabel.append(remember, '存入系统凭据库，下次打开可直接检测');
          const refresh = document.createElement('button'); refresh.textContent = '读取模型列表';
          refresh.addEventListener('click', () => busy(refresh,async () => {
            const result = await action('models',{catalog_id:data.catalog.catalog_id,source_alias:provider.source_alias},'模型列表已读取。');
            if (result) setModels(model,result.models,model.value);
          }));
          const importTarget = async () => {
            if (!nameInput.value.trim() || !model.value) return message('请填写测试名称并从列表选择模型。',true);
            const saveCredentials = Boolean(data.vault_available && remember.checked);
            const result = await action('catalog_select', {source_alias:provider.source_alias, model:model.value,
              display_name:nameInput.value,reasoning_effort:effort.value,catalog_id:data.catalog.catalog_id,
              save_credentials:saveCredentials}, saveCredentials
              ? '目标已导入，Key 已存入系统凭据库。'
              : '目标已导入，本次运行可直接检测。');
            if (result) await showAddedTarget(result.source_alias);
          };
          const button = document.createElement('button'); button.textContent = '导入目标'; button.addEventListener('click', () => busy(button,importTarget));
          row.append(nameInput,model,effort,refresh);
          if (data.vault_available) row.append(rememberLabel);
          row.append(button);
        } else if (provider.source_kind === 'relay') {
          const note = document.createElement('span'); note.textContent = '缺少可直接使用的专用 Key，不读取官方登录凭据。'; row.append(note);
        }
        container.append(row);
      });
    }
    if (u.local_status === 'ok') $('localUsage').textContent = `观察到本地 ${formatCount(u.observed_local_tokens)} token、${formatCount(u.observed_local_responses)} 条逐响应记录。历史渠道归属未知，未并入中转账单。`;
    else if (u.local_status === 'unavailable') $('localUsage').textContent = '本地用量暂不可读，请检查所选目录。';
    const rows = $('historyRows'); rows.replaceChildren();
    $('anomalyRows').replaceChildren();
    if (!data.history.length) { const row = document.createElement('tr'); cell(row, '暂无检测记录'); rows.append(row); }
    data.history.forEach((result, index) => {
      const row = document.createElement('tr');
      cell(row, new Date(result.evaluated_at).toLocaleString()); cell(row, targetLabel(data, result) + ' / ' + result.model);
      cell(row, runLabel(result)); cell(row, identityLabel(result.identity_state));
      cell(row, result.capability_state ? label(result.capability_state) : '—'); cell(row, label(result.status)); rows.append(row);
      const entry = historyEntry(data, index);
      if (entry) {
        const td = document.createElement('td');
        const open = document.createElement('button'); open.type = 'button'; open.textContent = '查看报告';
        open.addEventListener('click', () => openHistoryReport(entry)); td.append(open); row.append(td);
      } else cell(row, '详情暂不可用');
      if(result.detected_anomaly || result.status!=='ok' || result.network_failures || result.invalid_responses ||
        result.dimensions && result.dimensions.stability.status==='historical_decline_signal') {
        const item=document.createElement('li');
        const brief = entry?.report;
        const reason = brief?.diagnostics?.join('；') || brief?.headline || label(result.status);
        item.textContent=`${new Date(result.evaluated_at).toLocaleString()} · ${targetLabel(data, result)} · ${runLabel(result)} · ${reason}`;
        if (entry) {
          const open = document.createElement('button'); open.type = 'button'; open.textContent = '查看报告';
          open.addEventListener('click', () => openHistoryReport(entry)); item.append(open);
        }
        $('anomalyRows').append(item);
      }
    });
    document.querySelectorAll('.desktop-only').forEach(node => { node.hidden = !data.desktop; });
    document.querySelectorAll('.browser-only').forEach(node => { node.hidden = !!data.desktop; });
    if (data.desktop) $('notifications').textContent = desktopNotifications ? '关闭窗口提醒' : '开启窗口提醒';
    if (noticeId !== null && data.notification_id > noticeId) {
      if (data.desktop) post('desktop/notify', {}).catch(() => {});
      else if (typeof Notification !== 'undefined' && Notification.permission === 'granted')
        new Notification('中转模型检测出现异常线索', {body:'请在本地检测页面查看复测证据。异常不直接证明模型被替换。'});
    }
    noticeId = data.notification_id;
    if (failures.length) {
      const dialog = $('assessmentFailureDialog');
      const messages = $('assessmentFailureMessages');
      if (!dialog.open) messages.replaceChildren();
      failures.forEach(brief => {
        const line = document.createElement('p');
        line.textContent = [brief.headline, brief.next_step].filter(Boolean).join('。');
        messages.append(line);
      });
      if (!dialog.open) dialog.showModal();
    }
  }
  function poll() {
    if (!pollRequest) {
      pollRequest = fetch('state', {cache:'no-store'}).then(response => {
        if (!response.ok) throw new Error();
        return response.json();
      }).then(render).catch(() => {
        message('本机服务连接已断开。请确认启动窗口仍在运行。', true);
      }).finally(() => {
        pollRequest = null;
        clearTimeout(pollTimer);
        pollTimer = setTimeout(poll, state?.busy ? 400 : 2000);
      });
    }
    return pollRequest;
  }
  async function refreshState() {
    if (pollRequest) await pollRequest;
    await poll();
  }
  const referenceDialog = $('referenceDialog'), referenceForm = $('referenceForm');
  const deleteDialog = $('deleteDialog'), confirmDelete = $('confirmDelete');
  function openReference(targetId) {
    const target = state.targets.find(item => item.target_id === targetId);
    if (!target) return message(referenceErrors.target_not_found, true);
    const presets = state.official_presets || [];
    if (!presets.length) return message('暂时无法读取官方供应商列表，请刷新后重试。', true);
    referenceTargetId = targetId;
    referenceForm.reset();
    const select = referenceForm.elements.preset_id;
    select.replaceChildren(new Option('请选择官方供应商', ''),
      ...presets.map(preset => new Option(preset.label, preset.id)));
    select.value = target.reference_preset || '';
    referenceForm.elements.save_credentials.disabled = !state.vault_available;
    referenceForm.elements.save_credentials.checked = Boolean(state.vault_available && target.reference_saved);
    $('referenceClaim').textContent = '中转声明的型号 ' + target.model;
    $('referenceFeedback').textContent = state.vault_available ? '' : '系统凭据库暂不可用，Key 可在本次运行中使用。';
    referenceDialog.showModal();
  }
  referenceForm.elements.preset_id.addEventListener('change', () => {
    referenceForm.elements.api_key.value = '';
    referenceForm.elements.save_credentials.checked = false;
    $('referenceFeedback').textContent = '';
  });
  $('cancelReference').addEventListener('click', () => referenceDialog.close());
  referenceDialog.addEventListener('close', () => {
    referenceForm.reset();
    referenceTargetId = null;
  });
  referenceDialog.addEventListener('cancel', event => {
    if ($('saveReference').dataset.pending) event.preventDefault();
  });
  referenceForm.addEventListener('submit', event => {
    event.preventDefault();
    const fields = referenceForm.elements, feedback = $('referenceFeedback');
    const request = {target_id:referenceTargetId, preset_id:fields.preset_id.value,
      api_key:fields.api_key.value, save_credentials:!fields.save_credentials.disabled && fields.save_credentials.checked};
    busy($('saveReference'), async () => {
      $('cancelReference').disabled = true;
      fields.preset_id.disabled = fields.api_key.disabled = fields.save_credentials.disabled = true;
      feedback.textContent = '正在匹配官方同型号…';
      try {
        const result = await post('official_reference', request);
        fields.api_key.value = '';
        referenceDialog.close();
        await refreshState();
        const provider = presetLabel(state.official_presets || [], request.preset_id);
        const pending = result.reference_state === 'reference_pending' ? '。Key 待首次检测验证。' : '。';
        message('已匹配 ' + provider + ' · ' + result.reference_model + pending);
      } catch (error) {
        feedback.textContent = referenceErrors[error.message] || errors[error.message] || '无法保存官方参考，请检查设置后重试。';
      } finally {
        $('cancelReference').disabled = false;
        fields.preset_id.disabled = fields.api_key.disabled = false;
        fields.save_credentials.disabled = !state.vault_available;
      }
    });
  });
  function openDelete(target, card) {
    card.querySelector('.target-menu').open = false;
    const status = card.querySelector('.target-action-status');
    if (runningTarget(target)) {
      status.textContent = '这个目标正在检测，请先点击「停止本轮检测」，等检测结束后再删除。';
      card.querySelector('.cancel-target').focus();
      return;
    }
    status.textContent = '';
    deleteTargetId = target.target_id;
    $('deleteTargetName').textContent = card.querySelector('.target-name').textContent;
    $('deleteFeedback').textContent = '';
    deleteDialog.showModal();
  }
  $('cancelDelete').addEventListener('click', () => deleteDialog.close());
  deleteDialog.addEventListener('close', () => {
    const target = state.targets.find(item => item.target_id === deleteTargetId);
    if (target) $('target-' + target.source_alias)?.querySelector('.target-menu summary').focus();
    deleteTargetId = null;
  });
  deleteDialog.addEventListener('cancel', event => {
    if (confirmDelete.dataset.pending) event.preventDefault();
  });
  $('deleteForm').addEventListener('submit', event => {
    event.preventDefault();
    busy(confirmDelete, async () => {
      const targetId = deleteTargetId;
      const feedback = $('deleteFeedback');
      $('cancelDelete').disabled = true;
      feedback.textContent = '正在清理目标配置和 Key…';
      try {
        await post('target_delete', {target_id:targetId});
        if (pollRequest) await pollRequest;
        render({...state, targets:state.targets.filter(target => target.target_id !== targetId)});
        deleteDialog.close();
        (selectedTargetId ? targetPicker : $('addTarget')).focus({preventScroll:true});
        message('检测目标已删除，历史报告和用量已保留。');
        await poll();
      } catch (error) {
        const deletionErrors = {
          target_running:'这个目标正在检测。请关闭此窗口并停止本轮检测，结束后再删除。',
          vault_unavailable:'无法清理已保存的 Key。请确认系统凭据库可用后重试。',
          profiles_unavailable:'无法保存私人配置。请检查本机配置是否可写后重试。',
          target_delete_rollback_failed:'目标配置未删除，已保存 Key 无法恢复。请确认系统凭据库及配置可用后重试。',
          unknown_target:'检测目标已移除，请关闭窗口后刷新列表。'
        };
        feedback.textContent = deletionErrors[error.message] || errors[error.message] || '删除未完成，请稍后重试。';
      } finally {
        $('cancelDelete').disabled = false;
      }
    });
  });
  document.addEventListener('click', event => {
    document.querySelectorAll('.target-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  $('targetForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, data = Object.fromEntries(new FormData(form));
    data.max_output_tokens = Number(data.max_output_tokens); data.temperature = data.temperature === '' ? null : Number(data.temperature);
    data.stream = form.elements.stream.checked;
    data.save_credentials=form.elements.save_credentials.checked;
    data.models = Array.from(form.elements.model.options).map(option=>option.value).filter(Boolean);
    const result = await action('configure', data, '已添加目标，检测保持关闭。');
    if (result) {
      ['base_url','api_key'].forEach(name => { form.elements[name].value = ''; });
      await showAddedTarget(result.source_alias);
    }
  });
  $('budgetForm').addEventListener('submit', event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
    action('budget', {request_limit:Number(data.request_limit), token_limit:Number(data.token_limit)}, '每日预算已更新。');
  });
  $('observeForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget;
    if (await action('observe', {home:form.elements.home.value}, '只读观察已启动，原始数据不外发。')) form.reset();
  });
  $('catalogForm').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget;
    if (await action('catalog', Object.fromEntries(new FormData(form)), '已只读识别供应商目录，尚未发起检测。')) form.elements.path.value = '';
  });
  const readCatalog = (button,auto) => busy(button,async () => {
    $('catalogStatus').textContent = auto ? '正在查找并只读加载配置…' : '正在打开文件选择窗口，请选择配置或取消…';
    const result = await action('desktop/catalog',{source:$('catalogForm').elements.source.value,auto},'供应商目录已读取，请在下方选择模型、填写名称后导入或测试。');
    $('catalogStatus').textContent = $('message').textContent;
    return result;
  });
  $('chooseCatalog').addEventListener('click', event => readCatalog(event.currentTarget,false));
  $('autoCatalog').addEventListener('click', event => readCatalog(event.currentTarget,true));
  $('readModels').addEventListener('click', event => busy(event.currentTarget,async () => {
    const form = $('targetForm');
    const result = await action('models',{base_url:form.elements.base_url.value,api_key:form.elements.api_key.value,wire_api:form.elements.wire_api.value},'模型列表已读取，请从列表选择模型。');
    if (result) setModels(form.elements.model,result.models,form.elements.model.value);
  }));
  ['base_url','api_key','wire_api'].forEach(name => $('targetForm').elements[name].addEventListener('input', () => {
    setModels($('targetForm').elements.model,[],'','先读取中转模型列表');
  }));
  $('chooseHome').addEventListener('click', () => action('desktop/observe', {}, '选择已处理；只读观察不外传原始数据，取消选择保持现状。'));
  let estimateSequence=0, approvedEstimate=null, auditSubmitting=false, blockedReviewBudget=null;
  function openAudit(alias, mode, reviewOf=null) {
    audit = {source_alias:alias, mode};
    if (reviewOf) audit.review_of = reviewOf;
    $('auditTitle').textContent = reviewOf ? '用新题复核' : names[mode];
    $('auditDescription').textContent = reviewOf ? '初筛观察到中转答对数较少。复核将重新生成一批题，由中转和当前官方参考各作答一次。'
      : {assessment:'增加题目数量；匹配的官方参考会自动参加同题对照。',context:'按提示字符长度测试多跳检索。',reasoning:'同一批题比较 low / high 档位。',baseline:'登记实验指纹，7 天后不再自动比较。',identity_audit:'交错采集官方与中转响应，比较行为分布。'}[mode];
    $('auditSampleLabel').textContent = reviewOf ? '新题配对数（至少 40 对）' : '每类样本数 / 配对数';
    $('auditSamples').min = reviewOf ? '40' : '1';
    $('auditSamples').value = {assessment:40,context:3,reasoning:5,baseline:12,identity_audit:50}[mode];
    $('inputPrice').closest('details').hidden = mode === 'assessment';
    $('confirmAudit').textContent = reviewOf ? '确认并加入复核' : '加入检测队列';
    $('auditDialog').showModal();
    updateEstimate();
  }
  async function updateEstimate() {
    if (!audit || auditSubmitting) return;
    const sequence=++estimateSequence;
    const n = Number($('auditSamples').value);
    approvedEstimate=null;
    blockedReviewBudget=null;
    $('confirmAudit').disabled=true;
    $('retryEstimate').hidden=true;
    $('reviewBudgetShortcut').hidden=true;
    if (!$('auditSamples').checkValidity()) {
      $('auditEstimate').textContent='请输入 '+$('auditSamples').min+' 到 200 的整数。';
      return;
    }
    $('auditEstimate').textContent='正在本机估算预算…';
    const prices={};
    [['inputPrice','input_price'],['outputPrice','output_price'],['referenceInputPrice','reference_input_price'],['referenceOutputPrice','reference_output_price']].forEach(([id,key])=>{if($(id).value!=='')prices[key]=Number($(id).value);});
    try {
      const result=await post('estimate',{...audit,samples:n,prices}); if(sequence!==estimateSequence) return;
      const status = audit.review_of && result.status === 'budget_exhausted' ? '当前每日预算不足以复核。' : errors[result.status];
      $('auditEstimate').textContent=`${result.max_retry_requests ? '基础' : '最多'} ${requestSummary(result)} · 预留估算 ${formatCount(result.estimated_tokens)} token · 费用 ${result.estimated_cost==null ? '未知' : '$'+result.estimated_cost.toFixed(4)}。`+(status ? ' ' + status : '');
      if (audit.review_of && !result.matched_reference) {
        $('auditEstimate').textContent = '同型号官方参考当前不可用。请先恢复对照条件。';
        return;
      }
      if (audit.review_of && result.status === 'budget_exhausted') {
        const budget = state.budget;
        const requestLimit = budget.requests + (budget.held_requests || 0) + result.required_requests;
        const tokenLimit = budget.estimated_tokens + (budget.held_tokens || 0) + result.estimated_tokens;
        blockedReviewBudget = {
          requestLimit,
          text: `含已用及预留预算，预计每日上限需至少 ${formatCount(requestLimit)} 次请求、${formatCount(tokenLimit)} token。`
        };
        $('auditEstimate').textContent += ' ' + blockedReviewBudget.text;
        $('reviewBudgetShortcut').hidden=false;
      }
      if (result.status === 'ok') approvedEstimate = {samples:n, requests:result.required_requests};
      $('confirmAudit').disabled=!approvedEstimate;
    } catch (_) {
      if(sequence===estimateSequence) {
        $('auditEstimate').textContent='无法估算，请检查样本数和目标状态。';
        $('retryEstimate').hidden=false;
      }
    }
  }
  $('auditSamples').addEventListener('input', updateEstimate);
  $('retryEstimate').addEventListener('click', updateEstimate);
  $('reviewBudgetShortcut').addEventListener('click', () => {
    if (!blockedReviewBudget) return;
    const {requestLimit, text} = blockedReviewBudget;
    const current = state.budget;
    const fields = $('budgetForm').elements;
    fields.request_limit.value = current.request_limit;
    fields.token_limit.value = current.token_limit;
    $('auditDialog').close();
    (requestLimit > current.request_limit ? fields.request_limit : fields.token_limit).focus();
    message(text + ' 更新后可从检测卡重新打开复核。');
  });
  ['inputPrice','outputPrice','referenceInputPrice','referenceOutputPrice'].forEach(id=>$(id).addEventListener('input',updateEstimate));
  $('cancelCurrent').addEventListener('click',()=>action('cancel',{},'已请求停止；已发出的请求会继续计入用量。'));
  $('auditDialog').addEventListener('cancel', event => { if (auditSubmitting) event.preventDefault(); });
  $('auditDialog').addEventListener('close', () => {
    estimateSequence++;
    audit=null;
    approvedEstimate=null;
    blockedReviewBudget=null;
  });
  $('auditForm').addEventListener('submit', async event => {
    if (!event.submitter || event.submitter.value !== 'start') return;
    event.preventDefault();
    const n = Number($('auditSamples').value);
    if (auditSubmitting || !audit || !approvedEstimate || n !== approvedEstimate.samples) return;
    const request = {...audit, samples:n};
    if (audit.mode === 'assessment') request.expected_requests = approvedEstimate.requests;
    auditSubmitting = true;
    $('confirmAudit').disabled = $('cancelAudit').disabled = true;
    $('auditSamples').disabled = true;
    try {
      await post('run', request);
      $('auditDialog').close();
      message(request.review_of ? '已提交新题复核，请在检测卡查看进度。' : '已提交检查，请在结果区查看进度。');
      await refreshState();
    } catch (error) {
      approvedEstimate=null;
      $('auditEstimate').textContent=errors[error.message] || '提交未完成，请确认目标状态后重试。';
      $('retryEstimate').hidden=error.message==='assessment_changed' && Boolean(request.review_of);
    } finally {
      auditSubmitting = false;
      $('cancelAudit').disabled = false;
      $('auditSamples').disabled = false;
    }
  });
  $('notifications').addEventListener('click', async () => {
    if (state && state.desktop) {
      const enabled = !desktopNotifications;
      if (await action('desktop/notifications', {enabled}, enabled ? '窗口提醒已开启，出现新异常时闪烁任务栏；关闭应用后停止。' : '窗口提醒已关闭。')) desktopNotifications = enabled;
      return;
    }
    if (typeof Notification === 'undefined') return message('当前浏览器不支持桌面通知。', true);
    const permission = await Notification.requestPermission();
    message(permission === 'granted' ? '桌面提醒已开启，需要保持页面打开。' : '未开启桌面通知，仍可在页面查看结果。');
  });
  $('export').addEventListener('click', async () => {
    if (!state) return;
    const format=$('exportFormat').value;
    if (state.desktop) return action('desktop/export', {format}, '匿名报告已写入专用输出目录，已打开文件夹。');
    let blob;
    try {
      if(format==='html') {const response=await fetch('report',{cache:'no-store'});if(!response.ok) throw new Error();blob=await response.blob();}
      else blob=new Blob([JSON.stringify(exportSnapshot(state), null, 2)], {type:'application/json'});
    } catch (_) {return message('导出未完成，请检查本机服务。',true);}
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = 'relay-assessment.'+format; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  poll();
}());
