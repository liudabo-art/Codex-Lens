# 四家检测支持范围 / Four-family detection support

本页描述 **0.3.0 实验性桌面预览**，公开状态与可下载文件以 [GitHub Releases](https://github.com/liudabo-art/Codex-Lens/releases) 为准。旧版 v0.2.0 的安装包和标签保留。模型可以连接、软件流程通过、存在匹配参考、完成真实校准，是不同状态。当前没有已完成真实校准的型号。

This page describes the **0.3.0 experimental desktop preview**. Publication status and downloads are recorded by GitHub Releases; v0.2.0 assets and tags are retained. Connectivity, passing synthetic software checks, a matched reference and real model calibration are separate claims. No model is calibrated yet.

## 范围与优先级 / Scope and priority

| 优先级 | 家族 | 巡检 | 手动完整考试 | 官方对照 | 真实校准 |
| --- | --- | --- | --- | --- | --- |
| P0 | OpenAI GPT/Codex | `assessment-v4` | `exam-v2`, 120/180 | 同型号、可比参数 | 待取得官方访问并独立验证 |
| P0 | Anthropic Claude | `assessment-v4` | `claude-exam-v1`, 120/180 | 原生 Messages，同型号、可比参数 | 待独立验证 |
| P1 | DeepSeek | `assessment-v4` | `exam-v2`, 120/180 | 官方 DeepSeek Chat | 待独立验证 |
| P1 | Google Gemini | `assessment-v4` | `gemini-exam-v1`, 120/180 | 原生 generateContent，同型号、可比参数 | 待独立验证 |

OpenAI 与 Anthropic 并列最高优先。四家完整考试已接入共享软件链路，后续修复及真实校准仍优先处理 P0 的检测质量问题。其他厂商保留已有兼容配置、基础题与历史，暂停新增专用题集。只覆盖文本、代码、推理及可理解的报告；结构化文本题不代表原生工具调用支持，多模态和完整 Agent 评测后置。

OpenAI and Anthropic are co-P0. Other providers retain existing compatibility, configuration and history without new dedicated suites. This phase evaluates text, code and reasoning. Structured text tasks do not certify native tool use or agents.

## 独立试卷 / Independent papers

注册表 `exam_registry.py` 统一解析家族、题集版本、卷型、提示长度边界和重试额度。预估、运行、校准、模拟与逐题重建读取相同规格。错误的家族/版本组合直接拒绝，不回退为巡检。

- GPT/DeepSeek 保持既有 `exam-v2` 的题目、答案、种子及评分。12 份冻结试卷摘要作为回归样本；不把旧成绩按新卷重算。
- Claude 独立蓝图包含约束分配、规则优先级、别名可变状态、循环/异常边界、修订文档和指令作用域。Gemini 独立蓝图包含网格路径、方程/集合、排序与聚合、切片修复、时间/单位转换及嵌套结构定位。
- 两套新卷均有五类能力、三档复杂度、每组合四种结构。每 60 题均衡打散，120/180 题分别重复两/三组配额。独立答案程序从公开输入重新求解，覆盖边界和种子复现；难度名称仍属任务复杂度标签，不能当作已经测定的人群百分位。

The registry binds each family to its own paper contract. New native-family papers contain independent task structures and independent answer solvers. They share a scoring/reporting contract, not a claim that their raw scores rank different model families. Legacy GPT/DeepSeek papers retain their exact mappings.

## 参数、预算与作答 / Parameters, budget and completion

`model_capabilities.py` 按确切型号和协议维护经过官方文档核对的推理参数。模型默认与显式 `none` 不同。未核实型号只提供默认设置，不猜测预算或档位映射。界面过滤可选档位；已保存但不支持的设置保留显示，要求用户选择。参数错误在请求与计费预留前拦截，不换型号、不降档。具体支持与来源见该模块及 [官方参数资料](#parameter-sources--参数资料)。

官方参考匹配与实际请求使用同一校验。考试确认绑定家族、题集、卷型、双方型号、协议及输出/推理设置，排队开跑前复查。修改条件或预算需重新预览。

单测基础请求为 120/180，官方对照为 240/360。每题失败侧最多补两次，每侧全卷另有 20% 重试额度；最多预留 144/216 或 288/432 次。用户确认后才调整额度，费用不确定时显示未知。预算不足、认证/参数错误、截断、连续失败或取消时保留用量与进度，释放未用预留。周期任务不会启动考试。

每个必考侧全部完成才交卷；答错或完整格式失分计零并继续。连接失败不当作能力答错。原样本复试不额外增加题目数。

Reviewed exact-model settings are used consistently by official matching, previews and HTTP serialization. Unknown settings never cause a silent fallback. Budget estimates cover the complete confirmed paper plus bounded retries. Users decide the limits; insufficient budget stops work without reducing quality. All required sides must submit before a final grade is shown.

## 报告与研究 / Reports and research

主报告给出本场成绩、分项、官方差距、证据限制和下一步。中转更好、同分、证据不足与明显落后分别说明。桌面、历史和 HTML 使用同一后端结论。匿名 v2 继续保留版本、种子、逐题模板、评分状态和尝试次数，不含 Key、地址、私人名称或原始回答。官方登录业务、中转探针和官方参考用量继续分组。

冻结研究覆盖各家族的相应考试版本及 120/180 题，真实解析/重试/评分与正式引擎共用。旧清单严格核对源码哈希；需要旧源码复现或新源码重新初始化，不能重写清单冒充原研究。旧原生 `assessment-v4` 的默认参数和基础研究范围保持原限制。

源码研究工具在先导与正式验证中保留匿名双侧成绩计数、固定失败类别、失败侧与题号，分别报告完卷率、无法判断比例、复考分数分布及用量。不足两场完整成绩时标准差留空；旧记录没有绝对成绩时保留证据缺失，不补零。先导模板诊断用于描述选题线索，不自动筛题或提升已校准状态。研究变化控制在冻结前验证完整参数，已知等价设置不能冒充推理档位变化。

真实研究先 P0、后 P1。每个确切型号、配置和卷型分别做先导选题，冻结方案后用独立新题跨日期验证。公布失败及未交卷、误报、检出、无法判断、分数波动和开销。质量复核目标为 95% 区间误报上界 ≤5%、完整弱替换检出下界 ≥80%；软件测试不证明达标。没有官方 Key 时只做合成验收，不开始付费采样。[实测方案](CALIBRATION_PILOT_PLAN.md) · [统计与证据边界](METHODS.md)

Reports distinguish scores, observed differences and supported conclusions. Real studies require separately authorized official access and budgets. Each family/model/configuration/paper is validated independently; synthetic test counts are not detection-accuracy evidence.

Source research tools retain checked absolute exam counts and fixed terminal-failure evidence, separating pilot and validation completion, inconclusive rates, score spread and usage. Sample standard deviation remains null with fewer than two complete scores; absent legacy evidence never becomes zero. Template diagnostics and valid control settings support study review without changing the acceptance threshold or certifying a model.

## Parameter sources / 参数资料

参数表的确切条目与审阅日期以源码注释为准；接口支持不保证某个 Key 的权限或中转实际执行这些参数。

- [OpenAI model documentation](https://developers.openai.com/api/docs/models)
- [Claude thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) · [Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode)
- [Gemini generateContent thinking](https://aistudio.google.com/docs/thinking?generate-content=true)
