# 首批实测方案与预算 / Pilot study proposal

**2026-11-14 软件范围更新：** OpenAI／Anthropic 并列优先；新增 Claude/Gemini 完整考试与独立研究软件入口，分别使用 `claude-exam-v1`／`gemini-exam-v1`。GPT/DeepSeek 保持 `exam-v2`。各确切型号、设置和卷型分别冻结，参数以经过核实的支持表为准。现有候选和预算均待用户确认；没有官方 Key，本轮不采样。旧研究保留原清单及源码哈希，新源码需新建研究。[支持与研究边界](FOUR_FAMILY_DETECTION.md)

状态：**软件准备与合成验收阶段，尚无官方访问凭据，未开始真实采样。** 本文提供可审阅的研究输入与预算建议；不创建研究、不授权请求，也不代表型号已校准。每个家族、型号对、请求配置和卷型分别研究。

0.3.0 的 M3 工具已补齐双侧绝对成绩计数、分阶段完卷率／无法判断比例／复考波动、固定失败类别与来源。旧缺失不补零；冻结包含推理变化的研究前校验其完整设置并拒绝已知等价控制。新源码需重新初始化研究，不修改旧清单来放宽哈希。

## 首批候选

开发与真实研究均以 OpenAI／Anthropic 并列 P0，DeepSeek／Gemini 为 P1。下表既有 OpenAI／DeepSeek 候选保留作待核实输入；Claude／Gemini 的具体官方型号、参数和受控替代同样需单独核对，不能将表中顺序当成开发优先级。

| 家族 | 主型号候选 | 受控替代候选 | 协议与初始设置 |
| --- | --- | --- | --- |
| GPT/Codex | `gpt-6.1-sol` | `gpt-6-luna` | Responses；模型默认推理；输出上限 8192；流式 |
| DeepSeek | `deepseek-v4-pro` | `deepseek-flash` | DeepSeek Chat；模型默认推理；输出上限 8192；流式 |

候选来自 2026-11-13 查阅的 [OpenAI Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[OpenAI Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) 与 [DeepSeek 官方型号说明](https://api-docs.deepseek.com/quick_start/pricing/)。受控替代是否在本题集上更弱，需要先导验证，不提前认定。Key 可见性、生成权限、速率限制和实际可用版本均未核验。厂商可变别名不能当成不可变模型快照，正式研究须记录可取得的版本与适用日期；禁止自动换型号。

先做每个家族的 120 题标准卷，再独立研究 180 题加长卷。题量、五类能力、三个难度、完整交卷和失败侧重试要求不因预算降低。先导后若需改题，按新版本重新冻结，再用独立样本正式验证。

## 生成请求计划

基础范围包含正常同型号与完整弱替换两个场景，每场景 10 次先导、100 次正式验证。下表覆盖单个家族、单个型号对和单个卷型。

| 卷型／阶段 | 基础请求 | 额外重试上限 | 总请求上限 |
| --- | ---: | ---: | ---: |
| 120 题：一场双侧考试 | 240 | 48 | 288 |
| 120 题：20 场先导 | 4,800 | 960 | 5,760 |
| 120 题：200 场验证 | 48,000 | 9,600 | 57,600 |
| 120 题：整项研究 | 52,800 | 10,560 | 63,360 |
| 180 题：一场双侧考试 | 360 | 72 | 432 |
| 180 题：20 场先导 | 7,200 | 1,440 | 8,640 |
| 180 题：200 场验证 | 72,000 | 14,400 | 86,400 |
| 180 题：整项研究 | 79,200 | 15,840 | 95,040 |

正式验证分成三个按 UTC 日期递进的区段，各区段完成所有场景后再进入下一段。先导和正式验证使用独立种子。失败、取消和未交卷均保留，不无声补跑同一试验以排除失败。

## 可调整的默认预算建议

默认建议只覆盖**一场完整试验及其重试额度**，用户可调整并确认。建议不自动写入每日预算，不授权调用，也未核查当天已有消耗。

- 120 题双侧考试建议预留 288 次；180 题建议 432 次。
- token 建议沿用各题集规划器的保守预留。输出上限 8192 时，GPT/DeepSeek 的 120／180 题双侧试验分别为 3,612,672／5,419,008 token；Claude/Gemini 独立题集提示上界较大，对应 4,792,320／7,188,480 token。实际预览按用户选择的参数和题集重新计算，不沿用另一家族的预算。
- `calibration-plan` 单独显示用户额度及请求／token 缺口；低于完整试验要求时明确提示。实际采集仍需显式请求和 token 上限，运行中每次尝试受账本控制。额度不足时停止后续请求并保留结果；用户提高额度或另行安排完整试验，不自动降低试卷要求。
- 未提供可信价格及独立账单证据时，金额显示未知。token 预留不是供应商账单封顶；中转上报消耗也不是独立账单证据。

## 纯离线预览

以下命令只检查公开研究输入并输出 JSON。它不读保存目标、凭据、用量或研究数据库，不查询官方模型，不写入冻结清单。`frozen=false`、`collection_authorized=false` 和访问未核验状态始终保留。

```powershell
python -I -S -B run.py calibration-plan --family gpt --suite exam-v2 --primary-model gpt-6.1-sol --alternative-model gpt-6-luna --wire-api responses --samples 120 --max-output-tokens 8192 --stream --seed 42
python -I -S -B run.py calibration-plan --family deepseek --suite exam-v2 --primary-model deepseek-v4-pro --alternative-model deepseek-flash --wire-api deepseek --samples 180 --max-output-tokens 8192 --stream --seed 42
python -I -S -B run.py calibration-plan --family claude --suite claude-exam-v1 --primary-model claude-opus-4-6 --alternative-model claude-sonnet-4-6 --wire-api anthropic --samples 120 --max-output-tokens 8192 --seed 42
python -I -S -B run.py calibration-plan --family gemini --suite gemini-exam-v1 --primary-model gemini-3.1-pro-preview --alternative-model gemini-3-flash-preview --wire-api gemini --samples 180 --max-output-tokens 8192 --seed 42
```

可附加 `--request-limit` 和 `--token-limit` 检查用户拟定的单日容量。提示“满足拟定额度”仍不代表已核对当天余额或官方访问。预览不返回可直接采集的研究 ID；实际初始化另行生成并验证冻结清单。采集以清单为准，显式冲突的协议、推理、输出上限或流式参数在询问 Key、修改预算之前拒绝。

## Claude／Gemini 模块进度与边界

两家的原生基础研究与独立完整考试均已有软件入口。旧 `assessment-v4` 保留模型默认推理／温度限制；`claude-exam-v1` 与 `gemini-exam-v1` 在 `primary` 两场景中允许经过核实的确切型号参数，输出上限和流式选项分别冻结。GPT/DeepSeek 原 `exam-v2` 不跨家族复用；任何软件支持均不认证型号或真实能力。

Claude 与 Gemini 的推理参数支持与型号有关，参见 [Claude thinking troubleshooting](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting) 与 [Gemini thinking](https://aistudio.google.com/docs/thinking)。本轮保持现有 Messages／generateContent 协议，不迁移 API，也不猜测不同型号的推理参数映射。原生家族不支持的模拟或考试组合明确拒绝，不回退为 GPT。

Claude 完整考试的软件补齐与 OpenAI 同属首批 P0；通过首批完整软件链路后，再推进 Gemini 与 DeepSeek 的 P1 完善。缺少真实基础校准数据不阻塞软件开发，软件验收不授予真实准确率标记。所有实测结论限定家族、型号、任务版本、参数与时间，需各自研究与独立复核，不把 GPT 的实测保证外推到其他家族。

上述 Claude/Gemini 命令中的型号对仅展示软件输入，尚未核验实际访问、版本或强弱关系，不能当作真实研究已经选定。先导确认后再冻结，OpenAI／Anthropic 的采样优先于 P1 两家。

## 真正采样前的确认项

- 官方 API 访问与确切型号／可取得的版本可用。
- 用户确认卷型、请求参数、先导范围及请求／token 预算；Key 仅通过本机隐藏输入提供。
- 先导诊断审阅完成，再冻结正式题目、评分、参数、判定规则和独立验证日期安排。
- 正式结果完整公布误报、检出、无法判断、完卷率、复考波动、区间和开销。沿用误报 95% 区间上界 ≤5%、完整替换检出下界 ≥80% 的复核目标；统计通过仍需人工独立审阅。

English summary: keyless planning and native-family software support do not establish real calibration. Defaults suggest one complete trial including retries; users confirm actual limits separately. GPT/Codex, Claude, DeepSeek and Gemini registered exams and legacy native basic studies remain independently scoped and experimental.
