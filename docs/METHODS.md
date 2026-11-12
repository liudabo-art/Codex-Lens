# Evidence and calibration / 证据与校准

## What the product establishes / 结论边界

Results cover synthetic probe conditions, not all business traffic or a provider's intent. No supported model is currently calibrated. Connection, basic evaluation, matched reference and real calibration are separate states. Official login is never probed. Native Anthropic/Gemini software support does not validate their models or reuse a GPT calibration threshold as a certified result.

结果只覆盖本次合成探针条件，不能证明全部业务流量、模型身份或服务商动机。当前已校准型号名单为空。连接、基础评测、匹配参考、完成真实校准分别显示。官方登录不检测；原生 Claude/Gemini 适配不等于已验证型号，也没有“沿用 GPT 阈值就已校准”的声明。

## Tasks and four dimensions / 任务与四维报告

`quality-v2` generates constrained subset optimization, Python integer tracing, boundary-condition repair, deterministic structured data and **virtual tool arguments in text**. The tool-argument, document and structured-data prompts use the same answer envelope as the scorer. `context-v1` places a four-hop chain across generated distractors at approximately 4K/16K/64K characters. The report records actual prompt character lengths. `reasoning` repeats identical generated tasks with low/high settings and an optional independent reference. Unsupported settings fail explicitly.

质量任务包括约束最优解、代码追踪、边界条件修复、结构输出、文本中的虚拟工具参数；不是原生工具调用或完整 JSON Schema 验证，不执行生成代码。上下文题测多位置四跳关联，报告真实提示字符长度，不把单题成功外推成完整上下文窗口。推理专项同题比较 low/high，可带独立参考；响应慢、推理 token 多或某题答错都不单独判降配。

Reports show planned, attempted, correct, incorrect and unscorable assessment counts. Correctness and Wilson intervals describe scorable answers. The reliability denominator counts actual attempts, including failed attempts. Assessment `assessment-v4` recovers a unique complete JSON value from supported wrappers or prose while recording the format deviation for that side. A truncated answer remains unscorable. The `assessment-v4` history indicator uses four comparable complete runs with disjoint question seed intervals and flags a descriptive decline when both recent runs are at least 10 percentage points below both earlier runs. Comparison binds the owned target ID, model, protocol, suite, mode, reference binding and sample count. The UI comparison window uses the latest 200 records.

四维输出为能力质量、行为一致性、服务可靠性、长期稳定性。初筛按两侧记录计划、已尝试、答对、答错和无法评分。正确率与区间只覆盖可评分题，可靠性以实际尝试次数为分母。`assessment-v4` 可以从单个完整 JSON 代码块提取答案并单独记录该侧的格式偏差，截断仍无法评分。历史比较绑定目标 ID、模型、协议、任务版本、模式、参考和样本数。`assessment-v4` 使用四轮题目种子区间互不重叠的完整记录，两轮近期成绩都比前两轮低至少 10 个百分点才提示历史下降线索。页面比较窗口为最近 200 条。

Schema v1 history remains `legacy_unverified` and schema v2 remains `experimental`. The 10-question `assessment-v4` screen reports observed same-item gaps. A qualifying complete screen can open a per-side request preview for an explicitly confirmed independent review with 40–200 new pairs. A formal decision needs at least 40 complete pairs, a 10-point loss and a one-sided exact McNemar p-value within the daily allocation 0.01/[j(j+1)]. Descriptive or incomplete assessment runs consume no formal decision index. An incomplete comparison adds a whole-plan gap range by allowing each unknown score to vary between zero and one. This sensitivity range is separate from sampling confidence intervals. The report preserves task seeds and aggregate outcomes.

旧历史保留其验证状态，新结果继续标实验性。10 道题的初筛报告观察到的差距。符合复测条件时，用户可先分别预览两侧请求量，再确认用 40–200 对新题复测。正式判断要求至少 40 个完整配对、下降至少 10 个百分点，且单侧精确 McNemar 的 p 值符合日内分配阈值 0.01/[j(j+1)]。描述性和不完整的一键评估不消耗正式判定序号。不完整对照把每个未知得分按 0 到 1 变化，给出整批计划题的分差范围。抽样置信区间另行展示。报告保留种子和汇总结果。

Manual assessment and review retry connection errors and interrupted streams on the same question and side, with two extra attempts at most. The initial plan reserves the base requests. Retries use additional daily budget and are accounted separately from question scores. The third failure ends the run and retains preceding scores. An explicit authentication, unsupported parameter or output-limit error ends the run immediately. Scheduled assessments keep their fixed request plans. The default compatibility calibration path has no retries; explicit suite selection freezes and executes the retry policy for assessment-v4 or exam-v2.

手动检测和复核遇到断流或连接错误时，按相同参数在失败一侧最多重试两次。基础请求预留预算，重试使用额外的当日余额，单独计量。同题连续三次失败后中止本轮，保留之前的成绩。明确的认证失败、参数不支持和输出上限直接提示。周期检测仍按固定请求计划执行。受控校准的默认兼容路径不重试；显式选择 `assessment-v4` 或 `exam-v2` 时，冻结并执行相应重试策略及上限。

## Capability Exam / 能力考试

当前题集为 `exam-v2`，巡检评分为 `assessment-v4`。考试每个能力与难度组合使用四种结构，每 60 题各出现一次；120／180 题分别重复该配额两次／三次。新增题型包含最短路、依赖调度、寄存器与状态机、去重与插入边界、账目与区间关联、分组与稀疏结构转换。独立参考程序读取公开输入重新求解，检查标准答案及边界样例；题型的实测区分度仍待先导研究。

共享评分器按有界规则提取正文中唯一完整 JSON，并验证答案结构。冲突候选、重复字段、缺失字段、类型错误、非有限数值和过度嵌套保留细分原因。`item_results` 只保存题号、种子、模板、难度、来源、评分状态及请求次数。旧成绩按原版本保存，上次实测的格式失分不会推定追回。

The current suites are `exam-v2` and `assessment-v4`. Each exam skill and tier has four structures, one of each per 60-item block. Independent solvers verify published inputs and deterministic answers. The bounded scorer records unique JSON recovery and structured failure reasons. Per-item evidence contains anonymous grading metadata. Real discriminative power requires a separate pilot and held-out validation.

既有目标可在「检测设置与专项测试」修改输出 token 上限（128–16384）。推理模型可能同时把推理和答案计入此上限；遇到输出上限中止时，可提高额度后重新开考。考试确认页分别显示中转与官方参考的输出上限，并据此重新估算预算。修改参数后，已匹配的具名官方参考需重新匹配，旧的考试确认失效。

Existing targets expose an output token cap of 128–16384 in advanced test settings. Reasoning may share that cap with the answer. After an output-limit interruption, increase the cap before starting a new exam. The confirmation preview displays each side's cap and updates its budget estimate. Changed settings invalidate earlier exam approval and require rematching a named official reference.

`exam-v2` runs a manually confirmed 120- or 180-question exam for GPT/Codex and DeepSeek relays. It samples five skill groups at three difficulty levels, with four task structures in equal proportions per skill and difficulty. Every 60-question block has the same blueprint and a seed-shuffled order. Both sides of an optional official comparison get identical questions with alternating request order.

`exam-v2` 面向 GPT/Codex 和 DeepSeek 中转，手动运行 120 或 180 题。五类能力各含三档难度，每个题型与难度组合等量抽取四种结构。每 60 题使用相同配额并按种子打散。同型号官方对照使用同一批题，每题交替请求顺序。

Each correct answer earns one mark. A complete answer with recoverable JSON is graded by content and records a format deviation. An unparseable complete answer earns zero and records a format loss. A network error, interrupted stream or empty answer can retry the same question on the failed side up to twice. Each side also has a retry limit of one fifth of its paper size. An exam reserves the full base and retry allowance in the daily budget before starting. An incomplete paper publishes progress and usage. All required sides must submit before any final grade or paired verdict is available.

答对一题得一分。完整回复能恢复 JSON 时按内容判分，并记录格式偏差。无法解析的完整回复计零分并单列格式失分。连接错误、断流或空响应仅在失败侧重试原题，每题最多两次，每侧还受全卷题量五分之一的重试额度约束。开考前预留基础和重试预算。未交卷保留进度及用量。所有必考侧交卷后才出总分与对照判定。

An official comparison uses the existing minimum gap of 10 percentage points and the daily exact McNemar threshold on complete pairs. Scores describe the tested tasks, settings and time. Future calibration requires a separately authorized budget, pilot task selection and frozen validation with new papers across dates. Report repeated score variation, completion rate, false-positive and detection intervals, and cost by family and paper size. Frozen study commands support `assessment-v4` and explicit `--suite exam-v2` selection. The exam remains experimental until it is independently calibrated.

官方对照只在配对完整时按现有规则判断，要求至少 10 个百分点差距并通过单侧精确 McNemar 的日内阈值。成绩覆盖本场题型、请求设置和时间。实测需单独授权和预算，先导后冻结方案，用独立新卷跨日期验证，分别公布各家族和卷型的复考波动、完卷率、误报与检出区间及成本。下文冻结研究命令支持 `assessment-v4` 及显式选择的 `exam-v2`，考试独立校准前保留实验性标记。

## Reference provenance / 参考来源

Contemporaneous independent official API samples, seven-day historical official fingerprints, and user-imported numeric reference packs have distinct provenance. Packs require exact model/reference model/protocol/suite matching and age validation; imported packs are untrusted `user_history`, never promoted to official. There is no bundled verified public baseline yet. Suspect relay output is never automatically installed as a normal fingerprint. Desktop reference keys are tied to the selected official provider and region. A model listing checks visibility; a successful generation checks access for the selected settings. Cross-protocol pairing is limited to compatible default single-turn text settings. Short behavior evidence remains experimental under either protocol.

同期官方参考、7天内历史官方指纹、用户导入的数字参考分别标记。导入只接受精确匹配的数字特征，不自动信任为官方；当前没有随包提供已验证公共基线。可疑中转不会自动成为正常指纹。原生协议参考固定到对应厂商官方接口，绝不使用官方登录 token。

## Controlled studies / 受控校准工具

`calibration-simulate` is an offline, seeded comparison of 40, 80, 120 and 200 paired questions. It reports valid-pair coverage, verdict counts, missingness bounds and hypothetical request budgets for invented effects and failure patterns. It also exercises the current single-side engine and history rule with stable, sustained-decline and one-failed-round cases. These figures describe synthetic scenarios, and actual model accuracy requires a real study.

`calibration-simulate` 可离线比较 40、80、120、200 对题。它使用固定种子和假设的分差与缺失率，输出配对覆盖、判定计数、缺失范围和请求预算，并用实际单侧评估及趋势规则验证稳定、持续下降和单轮故障。模型实测另行校准。

Source CLI study commands do not discover credentials or call a model during initialization/reporting. Collection is an explicit paid action, one trial per command; it requires explicit daily request/token budgets and a hidden independently supplied official key. Do not run collection in normal tests/CI. Ordinary budget limits apply to every attempt, including failures. Ctrl+C preserves a partial, unresolved outcome and remaining reservations are released. Interrupted/failed trials cannot be silently replaced by recollecting the same index.

源码 CLI 初始化/汇总不请求模型。采集命令每次只采一个试验，必须明确双方总请求/token预算并隐藏输入独立官方 Key；这是单独付费授权步骤，本次开发未执行。所有尝试共享持久预算。中断会保留未完成结果，不能无声重跑同一编号并排除失败。崩溃可能留 collect.lock，应先确认没有采集进程，再人工处理锁；不自动抢占锁或重新采样。

```powershell
python -I -S -B run.py calibration-simulate --trials 1000 --seed 42
python -I -S -B run.py calibration-init --primary-model PUBLIC_MODEL_ID --alternative-model PUBLIC_WEAKER_ID --samples 40 --trials 100
python -I -S -B run.py calibration-report --study-id PRINTED_STUDY_ID
# Separate authorization/budget required; this next command spends API credit:
# python -I -S -B run.py calibration-collect --study-id PRINTED_STUDY_ID --phase pilot --scenario healthy --trial 0 --request-limit 1000 --token-limit 3000000
```

The source-only manifest freezes the implementation, requested model IDs, wire settings, seeds, sample size, scenario scope and decision index. Use a versioned official model ID where available. The default `--study-scope primary` runs healthy and full-substitution controls through the desktop assessment engine. At 40 pairs and 100 validation trials per scenario, it plans 17,600 generation attempts including pilots. The `extended` scope adds lower reasoning, randomized 10/30/50% mixtures and a separately labeled `context-v1` truncation control. Each scenario uses ten pilot trials followed by three balanced validation blocks on disjoint, ordered UTC dates with separate seeds. Complete every scenario in the current block before starting the next one. Requests in the study go to fixed official endpoints, where the experiment controls the routing.

源码校准冻结代码、请求型号、协议、种子、题量、场景和判定序号。能取得官方版本化 ID 时优先使用。默认 `--study-scope primary` 用桌面检测引擎验证正常与完整弱替换。40 对题、每场景 100 次验证加 10 次先导时，计划 17,600 次生成尝试。`extended` 另测低推理档、10/30/50% 随机混合，以及单独标记的 `context-v1` 截断专项。验证使用独立种子，分为三个均衡的 UTC 日期区段。每个区段完成全部场景后，才能在更晚日期开始下一段。真实采样独立授权和预算。旧冻结方案须重新初始化。

Acceptance uses two-sided exact Clopper–Pearson 95% intervals: healthy false-positive **upper bound ≤5%**, full substitution power **lower bound ≥80%**, and at least the frozen 100 (or explicitly increased) validation trials in each primary scenario. Unresolved healthy trials count against false-positive acceptance; unresolved substitutions count as misses. Mixed scenarios publish separate counts/intervals/budget curves without a minimum discovery promise. Request counts, reported tokens and unknown consumption are included; currency cost remains unknown without independent price/billing evidence. The study tests fixed alpha 0.005 and its frozen conditions; it does not validate all later daily alpha levels or every family. A statistical pass is only a review candidate: an independent audit must check pilot/task selection, blind holdout handling, controls, exact model versions, reproducibility and all failures before any verified registry entry. No real outcomes are published or fabricated here.

The review-candidate gate requires all controls in the frozen scope and validation on dates after pilots. `--calibration-audit-index` fixes the nominal threshold for that study and defaults to 1 (alpha 0.005). Fewer than 40 pairs yields descriptive data. 候选门槛要求完成冻结范围内的所有场景。可用 `--calibration-audit-index` 冻结判定序号，默认第 1 次。少于 40 对的研究用于描述。

Use the pilot task summaries and pilot spend to decide which task families merit a new frozen study. The validation report recomputes verdicts from paired counts and reports validation cost separately. Collecting across several later days helps assess time variation. The binomial intervals assume independent trials. 先导报告按题型和难度汇总成绩，并单列开销。调整选题后重新冻结，再采集未见过的验证样本。汇总按配对计数复算判定，置信区间以试验独立为前提。

验收用双侧精确95%区间，正常误报上界≤5%、完整替换检出下界≥80%，并达到预注册试验数。未决正常试验按不利情况纳入，未决替换按漏检计。混合场景单独公布预算/区间，不承诺少请求发现小比例替换。记录请求、上报token、未知消耗；无价格/账单证据时货币费用未知。研究固定alpha0.005，不外推到所有日内阈值和模型家族。统计达标仍只成为复核候选，需要人工独立审阅先导选题、盲测管理、版本与失败后才能入已验证名单。

## Research and licensing / 参考与许可

Original small procedural tasks borrow ideas, not code or datasets, from [ModelTrace](https://github.com/xqy2006/ModelTrace), [TraceOne](https://github.com/wangchao0708/TraceOne), [fpverify](https://github.com/Mohamed7415/fpverify), [RULER](https://github.com/NVIDIA/RULER), [Promptfoo](https://github.com/promptfoo/promptfoo), [Inspect](https://github.com/UKGovernmentBEIS/inspect_ai) and [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness). No IRIS noncommercial code/data is bundled. Review each new dependency/data license separately; this work does not choose or replace the repository license. Native protocol references: [Anthropic Messages](https://platform.claude.com/docs/en/api/messages), [Gemini content generation](https://ai.google.dev/api/generate-content).

Owned Windows vault blobs respect the [documented 5×512-byte CREDENTIALW limit](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw). Oversized values fail with a fixed message; users may keep keys in memory instead. No encrypted-file fallback is silently added.
