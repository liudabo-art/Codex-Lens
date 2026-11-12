"""Anonymous evidence reports: no verdict certifies model identity."""
from fractions import Fraction
import math

from .storage import safe_snapshot


def wilson(successes,total):
    if not total: return None
    z=1.959963984540054; p=successes/total; d=1+z*z/total
    center=(p+z*z/(2*total))/d
    radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [max(0,center-radius),min(1,center+radius)]


def upgrade(record):
    value=safe_snapshot(record)
    legacy=value.get('schema_version',1)<2 or value.get('evidence_level')=='legacy_unverified'
    value.update(schema_version=2,validation_state='experimental')
    value['evidence_level']='legacy_unverified' if legacy else (
        'matched_official_comparison' if value.get('provenance_level')=='same_time_official_reference' else
        'historical_reference' if value.get('baseline_id') else 'basic_observation')
    completed=value.get('capability_completed')
    correct=value.get('capability_correct',0)
    scored = value.get('capability_valid') if value.get('mode') == 'assessment' else completed
    exam = value.get('mode') == 'capability_exam'
    if exam and not _exam_submitted(value):
        scored = None
    accuracy=correct/scored if scored else None
    response_count=value.get('response_count',0)
    counts = value.get('assessment_counts')
    attempted = sum(row['attempted'] for row in counts) if counts else value.get('sample_count', response_count + value.get('network_failures', 0))
    if exam:
        sides = (value.get('exam') or {}).get('sides', [])
        attempted = sum(side.get('attempted', 0) + side.get('retry_requests', 0) for side in sides)
    stability=value.get('dimensions',{}).get('stability',{'status':'not_comparable'})
    value['dimensions']={
        'quality':{'accuracy':accuracy,'interval':wilson(correct,scored) if scored and not exam else None,
                   'valid_responses':value.get('capability_valid'),'sample_count':scored},
        'behavior':{'identity_state':value.get('identity_state','no_reference'),
                    'p_value':value.get('p_value'),'baseline_id':value.get('baseline_id')},
        'reliability':{'response_count':response_count,'sample_count':attempted,
                       'network_failures':value.get('network_failures',0),'invalid_responses':value.get('invalid_responses',0),
                       'latency_mean':value.get('latency_mean'),'latency_p95':value.get('latency_p95')},
        'stability':stability if not legacy else {'status':'not_comparable'}}
    value['recommendation']='review_reference' if value.get('detected_anomaly') else 'collect_more_evidence'
    return safe_snapshot(value)


ISSUES = {
    'output_limit': '输出达到上限', 'stream_interrupted': '响应中途断开',
    'empty_answer': '没有最终答案', 'response_filtered': '输出被过滤',
    'incomplete_output': '回答未完整结束', 'answer_format': '回答格式不符',
    'authentication_failed': 'Key 未通过认证', 'network_error': '网络连接失败',
    'unsupported_parameters': '接口不接受当前参数', 'rate_limited': '供应商限流',
    'reference_model_unavailable': '官方 API 不提供此型号或当前 Key 无权限',
    'reference_model_retired': '官方原版本已停用，旧型号 ID 已指向其他版本',
    'invalid_response': '接口返回格式无法解析', 'redirect_blocked': '请求发生跳转',
    'http_error': '供应商请求失败', 'remote_error': '供应商返回错误',
    'exam_changed': '考试条件已变更', 'exam_unsupported': '当前目标不支持能力考试',
    'reference_required': '官方同型号参考已不可用',
}
TASK_LABELS = {
    'constraints': '多步推理', 'code': '代码追踪', 'repair': '代码纠错',
    'structured': '结构化输出', 'tool_args': '工具参数', 'document': '文档规则',
    'code_branch': '分支与循环追踪', 'repair_edges': '边界条件纠错', 'constraints_multi': '多条件约束推理',
}


EXAM_TASK_LABELS = {
    'exam_reasoning': '多步推理', 'exam_code': '代码追踪', 'exam_repair': '边界纠错',
    'exam_information': '信息整合', 'exam_structure': '结构化指令',
}
EXAM_DIFFICULTY_LABELS = {1: '基础', 2: '进阶', 3: '挑战'}
EXAM_SOURCE_LABELS = {'relay': '中转', 'reference': '官方参考'}

GRADING_LABELS = {
    'ambiguous_answer': '存在多个答案', 'duplicate_keys': 'JSON 字段重复',
    'missing_answer': '缺少答案', 'missing_fields': '缺少必要字段',
    'unexpected_fields': '含有不允许的字段', 'answer_type': '答案类型不符',
    'invalid_json': '答案无法解析', 'nonfinite_number': '含非有限数值',
    'answer_too_large': '答案超过解析上限', 'answer_too_deep': '嵌套超过解析上限',
    'too_many_candidates': '答案候选过多',
}


def item_evidence(record):
    lines = []
    for item in record.get('item_results', []):
        source = EXAM_SOURCE_LABELS.get(item.get('source_kind'), '目标')
        result = ('正确' if item.get('correct') is True else '答案错误' if item.get('correct') is False
                  else '格式失分' if item.get('error_code') == 'answer_format'
                  else '请求未完成' if item.get('attempts') else '未作答')
        reason = GRADING_LABELS.get(item.get('grading_issue'))
        if item.get('format_state') == 'recovered_format':
            result += '，格式已恢复'
        if reason:
            result += '，' + reason
        lines.append(f'第 {item.get("question_number")} 题 · {source} · {result} · '
                     f'难度 {item.get("difficulty")} · 模板 {item.get("template")} · '
                     f'种子 {item.get("seed")} · 已发 {item.get("attempts", 0)} 次请求。')
    return lines


def _exam_submitted(record):
    exam = record.get('exam') or {}
    count = record.get('task_count')
    completed = {side.get('source_kind'): side.get('completed') for side in exam.get('sides', [])}
    required = {'relay': count, 'reference': count} if exam.get('comparison') == 'paired' else {'relay': count}
    return (record.get('status') == 'ok' and exam.get('submitted') is True and count in (120, 180)
            and completed == required)


def _exam_groups(sections, field):
    totals = {}
    for row in sections:
        by_side = totals.setdefault(row[field], {})
        marks = by_side.setdefault(row['source_kind'], [0, 0])
        marks[0] += row['correct']
        marks[1] += row['sample_count']
    return totals


def _exam_marks(marks):
    return '，'.join(f'{EXAM_SOURCE_LABELS[side]} {correct}/{total}' for side, (correct, total) in marks.items())


def _explain_exam(record):
    exam = record.get('exam') or {}
    count = record.get('task_count') or 0
    title = '能力考试 · ' + ('加长卷' if count == 180 else '标准卷')
    submitted = _exam_submitted(record)
    paired = exam.get('comparison') == 'paired'
    sides = exam.get('sides', [])
    pair = record.get('paired_result') or {}
    sections = exam.get('sections', [])
    next_step = '如需比较官方水平，可配置同型号官方参考后再考一场。'
    reference_note = '本场仅评估中转。'
    if paired:
        reference_note = f'同题官方对照。请求型号为中转 {record.get("model") or "未记录"}、官方 {record.get("reference_model") or "未记录"}。'
        next_step = '如需观察差距是否持续，可在同样的设置下另做一份新卷。'
    coverage = []
    diagnostics = []
    details = [f'题库 {record.get("suite_version") or "未记录"}，种子 {record.get("task_seed", "未记录")}，计划每侧 {count} 题。']
    format_notes = []
    score_tiles = []
    task_summary = []
    task_details = []
    for side in sides:
        name = EXAM_SOURCE_LABELS[side['source_kind']]
        coverage.append(f'{name}完成 {side["completed"]}/{side["sample_count"]} 题，已尝试 {side["attempted"]} 题。')
        if side.get('retry_requests'):
            coverage.append(f'{name}额外重试 {side["retry_requests"]} 次，已计入用量。')
        if side.get('format_failures'):
            format_notes.append(f'{name}格式失分 {side["format_failures"]} 道，计 0 分。')
        if side.get('format_recovered'):
            format_notes.append(f'{name}恢复格式 {side["format_recovered"]} 道，按答案内容判分。')
    for row in record.get('response_issues', []):
        code = row.get('error_code')
        if code not in ('answer_format', 'recovered_format'):
            name = EXAM_SOURCE_LABELS.get(row.get('source_kind'), '来源未记录')
            diagnostics.append(f'{name}{ISSUES.get(code, "请求未完成")} {row["sample_count"]} 次。')
    for field, name in (('comparison_conditions', '中转'), ('reference_comparison_conditions', '官方参考')):
        conditions = record.get(field)
        if conditions:
            temperature = conditions.get('temperature')
            details.append(f'{name}请求使用 {conditions.get("wire_api", "未记录")} 协议、'
                           f'{conditions.get("reasoning_effort") or "服务默认"}推理档位、'
                           f'输出上限 {conditions.get("max_output_tokens", "未记录")}、'
                           f'温度 {temperature if temperature is not None else "服务默认"}。')

    if submitted:
        headline = '能力考试已交卷'
        observed = '。'.join(f'{EXAM_SOURCE_LABELS[side["source_kind"]]} {100 * side["correct"] / count:.1f} 分，'
                            f'答对 {side["correct"]}/{count}' for side in sides) + '。'
        score_tiles = [{'label': EXAM_SOURCE_LABELS[side['source_kind']],
                        'score': f'{100 * side["correct"] / count:.1f} 分'} for side in sides]
        by_task = _exam_groups(sections, 'task_kind')
        by_difficulty = _exam_groups(sections, 'difficulty')
        if paired and pair.get('valid_pairs') == count:
            scores = {side['source_kind']: side['correct'] for side in sides}
            gap = scores['reference'] - scores['relay']
            if gap:
                direction = '低' if gap > 0 else '高'
                observed += f'中转{direction} {100 * abs(gap) / count:.1f} 个百分点。'
                if gap > 0:
                    deficits = [kind for kind, marks in by_task.items()
                                if marks['reference'][0] > marks['relay'][0]]
                    if deficits:
                        largest = max(deficits, key=lambda kind: by_task[kind]['reference'][0] - by_task[kind]['relay'][0])
                        observed += f'主要落后项为{EXAM_TASK_LABELS[largest]}。'
            else:
                observed += '两边答对数相同。'
            coverage.append(f'可比较 {count}/{count} 道同题。')
            p, alpha = pair.get('p_value'), pair.get('alpha')
            if pair.get('status') == 'degraded' and gap * 10 >= count and p is not None and alpha is not None and p <= alpha:
                headline = '本场同条件下，中转表现明显低于官方'
            else:
                reference_note += '本场未达到判定中转明显落后的门槛。'
            details.append(f'同题配对检验 p={p}，本轮阈值 {alpha}，最低判定差距 10 个百分点。')
        for kind, name in EXAM_TASK_LABELS.items():
            if kind in by_task:
                task_summary.append(f'{name} · {_exam_marks(by_task[kind])}。')
        for level, name in EXAM_DIFFICULTY_LABELS.items():
            if level in by_difficulty:
                task_summary.append(f'{name} · {_exam_marks(by_difficulty[level])}。')
        for section in sections:
            name = EXAM_TASK_LABELS[section['task_kind']]
            level = EXAM_DIFFICULTY_LABELS[section['difficulty']]
            side = EXAM_SOURCE_LABELS[section['source_kind']]
            task_details.append(f'{side} · {name} · {level} · 答对 {section["correct"]}/{section["sample_count"]}。')
    else:
        headline = '能力考试未交卷'
        observed = '本场只保留作答进度和已产生的用量。'
        status = record.get('status')
        source = EXAM_SOURCE_LABELS.get(record.get('failure_source'))
        question = record.get('failure_question')
        location = (source or '') + (f'第 {question} 题' if question else '')
        error_code = record.get('error_code')
        if status == 'budget_exhausted':
            diagnostics.insert(0, location + '因预算不足而停止。')
            next_step = '检查当日剩余预算，再预览一场新考试。'
        elif status == 'cancelled':
            diagnostics.insert(0, '用户取消了后续作答。')
            next_step = '准备好后可重新开始一场完整考试。'
        else:
            diagnostics.insert(0, location + ISSUES.get(error_code, '请求未完成') + '。')
            steps = {
                'authentication_failed': '检查失败侧的 API Key 后重新预览考试。',
                'unsupported_parameters': '检查失败侧支持的协议和推理档位后重新预览考试。',
                'output_limit': '检查输出上限和推理档位后重新预览考试。',
                'reference_required': '重新匹配同型号官方参考后开始新考试。',
                'exam_changed': '重新预览当前设置和预算后开始新考试。',
                'exam_unsupported': '选择受支持的 GPT/Codex 或 DeepSeek 中转模型后开始考试。',
            }
            next_step = steps.get(error_code, '检查失败侧的连接或接口状态后，重新开始一场完整考试。')

    details.extend(item_evidence(record))
    return {'task_label': title, 'headline': headline, 'capability': observed, 'comparison': reference_note,
            'reference_note': reference_note, 'identity': '型号身份仍待确认。',
            'diagnostics': diagnostics, 'observed': observed, 'coverage': coverage,
            'evaluated_at': record.get('evaluated_at', ''), 'next_step': next_step,
            'task_details': task_details, 'task_summary': task_summary, 'score_tiles': score_tiles,
            'details': details, 'limitations': '实验性考试。成绩仅覆盖本场题型、时间与请求设置。',
            'format_notes': format_notes}


def explain(record):
    """Derive ordinary-language copy exclusively from anonymous aggregate fields."""
    record = safe_snapshot(record)
    if record.get('mode') == 'capability_exam':
        return _explain_exam(record)
    n = record.get('capability_valid') or 0
    correct = record.get('capability_correct') or 0
    pair = record.get('paired_result') or {}
    paired_n = pair.get('valid_pairs') or 0
    headline = '本轮能力体检'
    comparison = '没有匹配的同型号官方参考。'
    if record.get('source_kind') == 'official_api':
        headline = '官方直连能力报告'
        comparison = '这轮测的是官方 API 本身。'
    elif record.get('reference_state') == 'reference_mismatch':
        comparison = '已配置参考，但型号或请求设置不一致。本轮只测中转能力。'
    elif record.get('reference_state') == 'reference_key_required':
        comparison = '未配置可用的同型号官方参考。本轮只测目标能力。'
    elif record.get('reference_state') == 'reference_unavailable':
        reason = ISSUES.get(record.get('reference_error'), '官方参考当前不可用')
        comparison = f'{reason}。本轮只测中转能力。'
    elif record.get('reference_state') in ('reference_matched', 'reference_pending') or (record.get('reference_preset') and pair):
        headline = '官方对照证据不足'
        comparison = '已选中官方参考。本轮尚未取得可评分的同题对照。'
        if paired_n and pair.get('reference_correct') is not None and pair.get('target_correct') is not None:
            delta = 100 * (pair['reference_correct'] - pair['target_correct']) / paired_n
            comparison = (f'官方 {pair["reference_correct"]}/{paired_n}，中转 {pair["target_correct"]}/{paired_n}。'
                          + (f'本轮中转低 {delta:g} 个百分点。' if delta > 0 else
                             f'本轮中转高 {-delta:g} 个百分点。' if delta < 0 else '本轮两边答对数相同。'))
            if pair.get('status') == 'degraded':
                headline = '本轮表现明显低于官方，建议复测'
            elif (pair.get('status') == 'no_detected_degradation' and
                  type(pair.get('regressions')) is int and wilson(pair['regressions'], paired_n)[1] <= .10):
                headline = '本轮未检出中转能力下降'
        if pair:
            comparison += f'共有 {paired_n}/{pair.get("attempted_pairs", paired_n)} 对题可以比较。'
        if record.get('model') and record.get('reference_model'):
            comparison += f'请求型号为中转 {record["model"]}、官方 {record["reference_model"]}。'
        if record.get('reference_error'):
            comparison += f'官方对照中止：{ISSUES.get(record["reference_error"], "请求未完成")}。'
    elif pair:
        headline = '旧版对照记录，证据待复核'
        comparison = '这是旧版对照记录。匹配条件和统计结果可在专业详情中查看。'
    capability = f'本轮答对 {correct}/{n} 道可评分题。' if n else '本轮没有可评分的能力题。'
    counts = record.get('assessment_counts') or []
    for side in counts:
        attempted, valid, correct = side['attempted'], side['valid'], side['correct']
        label = '官方参考' if side['source_kind'] == 'reference' else '本轮'
        coverage = f'{label}已尝试 {attempted}/{side["sample_count"]} 题，答对 {correct}，答错 {valid - correct}，无法评分 {attempted - valid}。'
        if side['source_kind'] and side['source_kind'] == record.get('source_kind'):
            capability = coverage
        elif side['source_kind'] == 'reference' and (attempted != valid or attempted != side['sample_count']):
            comparison += coverage
    if not counts and 0 < n < 10:
        capability += '样本较少，只能说明这几道题的表现。'
    identity = '本轮暂无可用的型号对照结论。'
    if record.get('identity_state') == 'identity_uncalibrated':
        identity = '已采集短行为样本，型号判断仍待校准。'
    elif record.get('identity_state') == 'invalid_probe':
        identity = '未取得可用的行为样本。'
        if not record.get('response_issues'):
            identity += '旧记录未保留具体原因。'
    source_labels = {'reference': '官方参考', 'relay': '检测目标', 'official_api': '检测目标'}
    diagnostics = [
        f'{source_labels.get(row.get("source_kind"), "来源未记录")} {ISSUES.get(row["error_code"], "请求未完成")} {row["sample_count"]} 次'
        for row in record.get('response_issues', []) if row.get('error_code') != 'recovered_format'
    ]
    if not diagnostics and record.get('error_code'):
        diagnostics = [ISSUES.get(record['error_code'], '请求未完成')]
    elif not diagnostics and record.get('reference_error'):
        diagnostics = [f'官方参考 {ISSUES.get(record["reference_error"], "请求未完成")}']
    failure_source = source_labels.get(record.get('failure_source'))
    error_code = record.get('error_code')
    if failure_source and record.get('status') == 'budget_exhausted':
        headline = f'检测中止，{failure_source}重试预算不足'
    elif failure_source and error_code in ('network_error', 'stream_interrupted'):
        headline = f'检测中止，{failure_source}连续连接失败' if error_code == 'network_error' else f'检测中止，{failure_source}响应反复中断'
    elif failure_source:
        headline = f'检测中止，{failure_source}{ISSUES.get(error_code, "请求未完成")}'
    elif record.get('status') == 'budget_exhausted':
        headline = '预算不足，检测未完成'
    elif record.get('status') == 'cancelled':
        headline = '检测已取消'
    elif record.get('status') != 'ok':
        headline = '检测未完成'
    reference_note = comparison
    # Observed scores and uncertainty are shared by the live UI, history and HTML.
    # A partial run may retain useful scores; neither cancellation nor formatting
    # recovery changes a valid answer into an incorrect answer.
    observed = f'目标答对 {record.get("capability_correct", 0)}/{n} 道可评分题。' if n else '本轮没有可评分的能力题。'
    score_tiles = []
    coverage = []
    for side in counts:
        label = source_labels.get(side.get('source_kind'), '来源未记录')
        coverage.append(f'{label}已尝试 {side["attempted"]}/{side["sample_count"]} 题，'
                        f'可评分 {side["valid"]}，答对 {side["correct"]}，'
                        f'答错 {side["valid"] - side["correct"]}，无法评分 {side["attempted"] - side["valid"]}。')
    if paired_n and pair.get('target_correct') is not None and pair.get('reference_correct') is not None:
        delta = 100 * (pair['reference_correct'] - pair['target_correct']) / paired_n
        observed = f'官方 {pair["reference_correct"]}/{paired_n}，中转 {pair["target_correct"]}/{paired_n}。'
        points = f'{abs(delta):.1f}'.rstrip('0').rstrip('.')
        observed += (f'本轮中转低 {points} 个百分点。' if delta > 0 else
                     f'本轮中转高 {points} 个百分点。' if delta < 0 else '本轮两边答对数相同。')
        score_tiles = [{'label': '中转', 'score': f'{pair["target_correct"]}/{paired_n}'},
                       {'label': '官方', 'score': f'{pair["reference_correct"]}/{paired_n}'}]
        reference_note = '本轮使用同题官方对照。'
        if record.get('model') and record.get('reference_model'):
            reference_note = f'请求型号为中转 {record["model"]}、官方 {record["reference_model"]}。'
        if record.get('reference_error'):
            reference_note += f'官方对照中止：{ISSUES.get(record["reference_error"], "请求未完成")}。'
    if pair:
        planned = pair.get('planned_pairs', pair.get('attempted_pairs', paired_n))
        coverage.append(f'可比较 {paired_n}/{planned} 对计划题目；只比较两边均可评分的同题答案。')
    if record.get('retry_requests'):
        retries = '，'.join(f'{source_labels.get(side["source_kind"], "来源未记录")} {side["retry_requests"]} 次'
                           for side in counts if side.get('retry_requests'))
        coverage.append(f'额外重试 {record["retry_requests"]} 次（{retries}），已计入用量。')
    details = []
    quality = record.get('dimensions', {}).get('quality', {})
    interval = quality.get('interval')
    if quality.get('accuracy') is not None:
        quality_line = f'可评分题正确率 {100*quality["accuracy"]:.1f}%。'
        if interval and len(interval) == 2:
            quality_line += f'二项模型下的 95% Wilson 区间：{100*interval[0]:.1f}%–{100*interval[1]:.1f}%；不代表真实业务准确率。'
        details.append(quality_line)
    reliability = record.get('dimensions', {}).get('reliability', {})
    if reliability:
        details.append(f'服务可靠性：返回 {reliability.get("response_count", 0)}/{reliability.get("sample_count", 0)} 次；'
                       f'请求失败 {reliability.get("network_failures", 0)} 次；无效响应 {reliability.get("invalid_responses", 0)} 次。')
        if reliability.get('latency_p95') is not None:
            details.append(f'响应时延 P95：{reliability["latency_p95"]:.2f} 秒。')
    stability = record.get('dimensions', {}).get('stability', {}).get('status')
    if stability:
        labels = {'historical_decline_signal': '历史下降线索，需复核', 'no_detected_deviation': '可比历史窗口未见持续下降',
                  'not_comparable': '条件不匹配，无法比较', 'insufficient_data': '独立完整轮次不足'}
        details.append('历史趋势：' + labels.get(stability, '尚不可判断') + '。')
    bounds = pair.get('loss_bounds')
    if bounds and len(bounds) == 2:
        details.append(f'计入缺失配对的最好／最坏情况：官方减中转的正确率差为 {100*bounds[0]:g} 至 {100*bounds[1]:g} 个百分点。'
                       '这是缺失结果的可能范围，不是置信区间。')
    if pair:
        details.append(f'配对检验：p={pair.get("p_value", "未取得")}；阈值={pair.get("alpha", "未分配")}。')
    for field, label in (('comparison_conditions', '目标请求设置'), ('reference_comparison_conditions', '官方请求设置')):
        conditions = record.get(field)
        if conditions:
            details.append(f'{label}：协议 {conditions.get("wire_api", "未记录")}；推理 {conditions.get("reasoning_effort") or "服务默认"}；'
                           f'输出上限 {conditions.get("max_output_tokens", "未记录")}；温度 {conditions.get("temperature") if conditions.get("temperature") is not None else "服务默认"}。')
        elif field == 'reference_comparison_conditions' and pair:
            details.append('官方请求设置：旧记录未保留，不能推定与当前设置一致。')
    details.append(f'任务版本 {record.get("suite_version", "未记录")}；题目种子 {record.get("task_seed", "未记录")}；'
                   f'计划题数 {record.get("task_count", "未记录")}。')
    task_details = []
    groups = {}
    for task in record.get('assessment_tasks', []):
        group = groups.setdefault(task.get('task_kind'), dict.fromkeys(('attempted', 'valid', 'correct', 'valid_pairs', 'target_correct', 'reference_correct'), 0))
        for key in group:
            group[key] += task.get(key) or 0
        label = TASK_LABELS.get(task.get('task_kind'), '其他能力题')
        if task.get('difficulty') is not None:
            label += f'（难度 {task["difficulty"]}）'
        line = f'{label}：答对 {task.get("correct", 0)}/{task.get("valid", 0)} 道可评分题，尝试 {task.get("attempted", 0)} 题。'
        if task.get('valid_pairs'):
            line += f'同题对照：中转 {task.get("target_correct", 0)}/{task["valid_pairs"]}，官方 {task.get("reference_correct", 0)}/{task["valid_pairs"]}。'
        task_details.append(line)
    def task_gap(task):
        pairs = task['valid_pairs']
        return Fraction(task['reference_correct'] - task['target_correct'], pairs) if pairs else 0

    task_summary = []
    for kind, task in sorted(groups.items(), key=lambda item: -abs(task_gap(item[1]))):
        label = TASK_LABELS.get(kind, '其他能力题')
        pairs = task['valid_pairs']
        if pairs:
            delta = task_gap(task)
            points = f'{float(abs(delta) * 100):.1f}'.rstrip('0').rstrip('.')
            difference = f'低 {points} 个百分点' if delta > 0 else f'高 {points} 个百分点' if delta < 0 else '答对数相同'
            task_summary.append(f'{label}：中转 {task["target_correct"]}/{pairs}，官方 {task["reference_correct"]}/{pairs}；{difference}。'
                                + (f'另有 {task["attempted"] - pairs} 题无法配对。' if task['attempted'] > pairs else ''))
        else:
            task_summary.append(f'{label}：答对 {task["correct"]}/{task["valid"]} 道可评分题；尝试 {task["attempted"]} 题。'
                                + ('暂无可比较的同题对照。' if pair else ''))
    for row in record.get('reasoning_comparison', []):
        task_summary.append(f'推理 {row.get("effort", "未记录")}：答对 {row.get("capability_correct", 0)}/{row.get("sample_count", 0)} 题。')
    for row in record.get('context_results', []):
        task_summary.append(f'上下文 {row.get("context_characters", 0)} 字符：答对 {row.get("capability_correct", 0)}/{row.get("sample_count", 1)} 题。')
    format_notes = [f'{source_labels.get(row.get("source_kind"), "来源未记录")}：{row["sample_count"]} 次格式恢复，答案已评分。'
                    for row in record.get('response_issues', []) if row.get('error_code') == 'recovered_format']
    next_step = '增加独立新题样本，并核对两边请求条件；本轮不能认证模型身份。'
    if not pair and record.get('source_kind') != 'official_api':
        if record.get('status') == 'ok' and stability == 'historical_decline_signal':
            headline = '本轮能力结果，近期成绩有下降迹象'
            next_step = '核对中转近期的型号和设置，再用新题复测。'
        else:
            next_step = '继续用同一设置积累历史结果；如需比较官方水平，可添加同型号官方参考。'
    elif record.get('source_kind') == 'official_api':
        next_step = '可增加独立新题，观察本轮能力表现能否复现。'
    elif (record.get('status') == 'ok' and not record.get('review_of') and paired_n == 10
          and pair.get('planned_pairs', pair.get('attempted_pairs')) == 10
          and (pair.get('accuracy_loss') or 0) >= .10):
        next_step = '先预览请求量，再决定是否用新题复核。'
    if diagnostics:
        next_step = '先处理上述来源对应的请求问题，再运行完整的一轮；缺失答案不等于答错。'
    if record.get('status') in ('cancelled', 'budget_exhausted'):
        next_step = ('检查剩余预算后' if record['status'] == 'budget_exhausted' else '准备好后') + '重新运行完整的一轮；保留的分数仅代表已完成题目。'
    elif failure_source and error_code == 'output_limit':
        next_step = '检查输出上限和推理档位，再重新开始检测。'
    elif failure_source and error_code == 'authentication_failed':
        next_step = f'检查{failure_source}的 API Key，再重新开始检测。'
    elif failure_source and error_code == 'unsupported_parameters':
        next_step = f'检查{failure_source}支持的协议和参数，再重新开始检测。'
    limitations = '实验性合成题结果，仅代表本轮可评分样本；不认证模型身份，也不代表真实业务能力。'
    if pair and paired_n < pair.get('planned_pairs', pair.get('attempted_pairs', paired_n)):
        if record.get('status') == 'ok':
            headline = '对照未完整完成，暂无法判断能力下降'
        limitations += '部分计划题目无法比较，不能据此得出完整对照结论。'
    if record.get('review_source_deleted'):
        coverage.append('这次复核的初筛记录已删除，复核结果独立保留。')
    details.extend(item_evidence(record))
    return {'headline': headline, 'capability': capability, 'comparison': comparison, 'reference_note': reference_note,
            'identity': identity, 'diagnostics': diagnostics, 'observed': observed, 'coverage': coverage,
            'evaluated_at': record.get('evaluated_at', ''), 'next_step': next_step,
            'task_details': task_details, 'task_summary': task_summary, 'score_tiles': score_tiles,
            'details': details, 'limitations': limitations, 'format_notes': format_notes}


def trend(records):
    records = [row for row in records if row.get('mode') != 'capability_exam']

    def completed(row):
        base = (row.get('status') == 'ok' and row.get('capability_completed') and
                row.get('capability_valid') == row.get('capability_completed') and
                not row.get('network_failures') and not row.get('invalid_responses'))
        if row.get('suite_version') in ('assessment-v3', 'assessment-v4') or (row.get('suite_version') == 'assessment-v2' and row.get('task_count') is not None):
            return base and type(row.get('task_count')) is int and row['task_count'] > 0 and row['task_count'] == row['capability_completed'] and type(row.get('task_seed')) is int
        return base
    dated=sorted((r for r in records if r.get('target_id')),key=lambda r:r.get('evaluated_at',''))
    if not dated: return {'status':'insufficient_data','sample_count':0}
    latest=dated[-1]
    if not completed(latest):
        return {'status':'not_comparable','sample_count':len(dated)}
    rows=[r for r in records if r.get('target_id') and completed(r)]
    rows.sort(key=lambda r:r.get('evaluated_at',''))
    if len(rows)<2: return {'status':'insufficient_data','sample_count':len(rows)}
    newest=rows[-1]
    binding=('target_id','model','protocol_id','suite_version','mode','reference_model','reference_preset',
             'reference_protocol_id','sample_count')
    previous=[r for r in rows[:-1] if all(r.get(k)==newest.get(k) for k in binding)]
    if not previous: return {'status':'not_comparable','sample_count':len(rows)}
    if newest.get('suite_version') in ('assessment-v2', 'assessment-v3', 'assessment-v4'):
        candidates = [*previous, newest]
        if newest.get('suite_version') in ('assessment-v3', 'assessment-v4') or all(type(row.get('task_count')) is int for row in candidates):
            window = []
            for row in reversed(candidates):
                if type(row.get('task_count')) is not int or type(row.get('task_seed')) is not int:
                    continue
                start, end = row['task_seed'], row['task_seed'] + row['task_count']
                if all(end <= kept['task_seed'] or start >= kept['task_seed'] + kept['task_count'] for kept in window):
                    window.append(row)
                if len(window) == 4:
                    break
            window.reverse()
        else:
            unique = {row['task_seed']: row for row in candidates if type(row.get('task_seed')) is int}
            window = sorted(unique.values(), key=lambda row: row['evaluated_at'])[-4:]
        if len(window) < 4:
            return {'status': 'insufficient_data', 'sample_count': len(window)}
        scores = [Fraction(row.get('capability_correct', 0), row['capability_completed']) for row in window]
        earlier, recent = scores[:2], scores[2:]
        decline = min(earlier) - max(recent) >= Fraction(1, 10)
        return {'status': 'historical_decline_signal' if decline else 'no_detected_deviation',
                'accuracy_change': float((sum(recent) - sum(earlier)) / 2), 'sample_count': 4,
                'provenance_level': 'user_history'}
    before=previous[-1]
    difference=newest.get('capability_correct',0)/newest['capability_completed']-before.get('capability_correct',0)/before['capability_completed']
    return {'status':'historical_decline_signal' if difference<=-0.1 else 'no_detected_deviation',
            'accuracy_change':difference,'sample_count':len(previous)+1,'provenance_level':'user_history'}


def comparisons(records):
    groups={}
    for row in records:
        if row.get('target_id') and row.get('mode') in ('quality','quality_audit','context','assessment'):
            groups.setdefault(row['target_id'],[]).append(row)
    result=[]
    for target_id,rows in groups.items():
        latest=max(rows,key=lambda r:r.get('evaluated_at',''))
        result.append({'target_id':target_id,'source_alias':latest.get('source_alias'),'model':latest.get('model'),
                       'suite_version':latest.get('suite_version'),'protocol_id':latest.get('protocol_id'),
                       'mode':latest.get('mode'),'last_result':upgrade(latest),'trend':trend(rows)})
    return safe_snapshot(result)
