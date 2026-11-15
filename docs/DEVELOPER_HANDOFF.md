# 开发交接与当前进度 / Developer handoff

更新日期：**2026-11-15**。本页是接手工作的起点；逐次完成记录见 [WORKLOG](../WORKLOG.md)，实际检查见 [VERIFICATION](VERIFICATION.md)，用户可见变化见 [CHANGELOG](../CHANGELOG.md)。修改前先读 [AGENTS](../AGENTS.md) 与 [SECURITY](../SECURITY.md)。

English summary: the 0.3.0 software baseline supports dedicated GPT/Codex, Claude, DeepSeek and Gemini exams. Software checks and research evidence tooling are complete; real model calibration still requires authorized official access and budgets. OpenAI and Anthropic are co-P0. This independent repository will integrate with Token Usage Monitor through the anonymous v2 contract. Verify publication independently; a local commit is not a published Release.

## 1. 接手时先确认版本

- 开发主体是 **[liudabo-art/Codex-Lens](https://github.com/liudabo-art/Codex-Lens)**，独立于 Token 监视器主项目。
- 当前安装包源码版本为 **0.3.0**，以根目录 [VERSION](../VERSION) 为准。发布源码提交为 [`5038acb`](https://github.com/liudabo-art/Codex-Lens/commit/5038acb62bb1137b5a99c0d48171baacd8193030)，作者为 `liudabo-art`；`main` 与版本发布分支已核对一致。
- **0.3.0 已于北京时间 2026-11-15 12:43:39 公开为实验性预发布。** [五目标原生构建及发布](https://github.com/liudabo-art/Codex-Lens/actions/runs/43676237351)与[版本分支合成检查](https://github.com/liudabo-art/Codex-Lens/actions/runs/43676237353)通过；[Release](https://github.com/liudabo-art/Codex-Lens/releases/tag/v0.3.0)的 8 个安装／便携包、校验文件及标签来源已核对。后续交接文档提交与安装包源码分别管理，复现安装包请使用该标签。
- 0.2.0 的标签、安装包及历史成绩保留。安装包版本、题集版本、匿名 API 版本分别管理，不能一并重标。

## 2. 当前完成到哪里

| 阶段 | 软件交付状态 | 仍需完成的证据 |
| --- | --- | --- |
| M0 规范与路线 | 已完成。四家专用范围和优先级已写入 AGENTS 与路线图。 | 后续改动持续遵循规范。 |
| M1 OpenAI／Anthropic | 已完成首批软件链路。巡检、120／180 题考试、可匹配官方对照、参数与预算、重试、报告已接通。 | 确切型号的题目区分度和真实检测质量未校准。 |
| M2 DeepSeek／Gemini | 已完成软件链路。DeepSeek 保留旧卷，Gemini 使用独立试卷及原生协议。 | 每家独立实测，不沿用 P0 的效果结论。 |
| M3 研究工具 | 已完成离线预览、冻结条件校验、逐题身份核验、模板诊断、双侧成绩计数和失败证据。 | 无官方 Key，尚未开始真实先导和跨日期验证。 |
| 跨平台交付 | 五个原生目标、包／worker／资源与安装冒烟通过，8 个包及校验清单已公开。 | 完整原生 GUI 人工验收另行记录，不能由打包成功代替。 |

最新发布前回归为 **385 项 Python、25 项前端检查通过**，均使用合成数据；命令、日期、范围与限制见 [验证记录](VERIFICATION.md)。这些数量不代表模型准确率。

优先级保持 **OpenAI GPT/Codex 与 Anthropic Claude 并列 P0；DeepSeek 与 Google Gemini 为 P1**。其他厂商保留已有兼容、配置与历史，本阶段不新增专用题集。当前只覆盖文本、代码与推理；原生工具调用、多模态和完整 Agent 评测后置。[支持矩阵](FOUR_FAMILY_DETECTION.md)

## 3. 修改入口与关键约束

| 工作内容 | 优先阅读的代码／文档 |
| --- | --- |
| 家族、卷型与预算规格 | [exam_registry.py](../relay_auditor/exam_registry.py)、[planning.py](../relay_auditor/planning.py) |
| 出题、答案与评分 | [exam_generators.py](../relay_auditor/exam_generators.py)、[native_exam_generators.py](../relay_auditor/native_exam_generators.py)、[grading.py](../relay_auditor/grading.py) |
| 完卷、失败侧重试与取消 | [exam.py](../relay_auditor/exam.py)、[controller.py](../relay_auditor/controller.py) |
| 型号／参数、官方匹配和传输 | [model_capabilities.py](../relay_auditor/model_capabilities.py)、[official.py](../relay_auditor/official.py)、[adapters.py](../relay_auditor/adapters.py)、[transport.py](../relay_auditor/transport.py) |
| 同一结论、历史与匿名导出 | [reports.py](../relay_auditor/reports.py)、[storage.py](../relay_auditor/storage.py)、[exporting.py](../relay_auditor/exporting.py) |
| 研究预览、采集与复算 | [calibration_readiness.py](../relay_auditor/calibration_readiness.py)、[calibration.py](../relay_auditor/calibration.py)、[calibration_metrics.py](../relay_auditor/calibration_metrics.py)、[calibration_cli.py](../relay_auditor/calibration_cli.py) |
| 页面与图文手册 | [app.js](../relay_auditor/web/app.js)、[手册内容源](../relay_auditor/web/manual/content.json)、[手册生成器](../build_tools/manual_docs.py) |
| 架构、公开字段与构建 | [FILE_GUIDE](../FILE_GUIDE.md)、[EXTENDING](EXTENDING.md)、[RELEASING](RELEASING.md) |

以下约束在接手时必须保留：

1. **试卷不混用。** GPT／DeepSeek 为 `exam-v2`，Claude 为 `claude-exam-v1`，Gemini 为 `gemini-exam-v1`。注册表统一供预估、运行、校准、模拟和逐题重建使用；不支持的组合直接拒绝。
2. **旧卷不重算。** GPT／DeepSeek 的原题、答案、种子映射和评分保持兼容。[旧固定卷](../tests/legacy_exam_papers.json) 与[原生固定卷](../tests/native_exam_papers.json) 是回归依据。公开后改题或改评分需要新版本，不能仅更新哈希让错误消失。0.3.0 发布前的 Claude 切片文字修正已单独记录，答案和种子未变。
3. **冻结研究不迁就新源码。** 清单严格校验源码哈希。用对应旧源码复现旧研究，或为新源码初始化新研究；不能修改旧清单绕过校验。记录形状兼容不豁免源码条件。
4. **参数与预算不静默降级。** 未核实型号只开放默认设置；不支持的旧设置提示用户处理。确认绑定具体试卷及双方请求条件，排队后再次校验。预算不足停止并保留证据，不降低题量、难度或推理档位。
5. **未交卷不给最终成绩。** 必考侧都完成后才结算；完整答错和格式失分计零并继续。断连只重试原题失败侧，已完成作答不反复评分。取消、预算中断和终止故障保留进度及用量。
6. **缺失证据不补零。** 先导与验证分开统计；旧记录缺少绝对成绩或失败原因时显示不可用。只用完整且有成绩证据的试验计算复考分布，不足两场时样本标准差为空。[方法与统计规则](METHODS.md)

## 4. 下一步按什么顺序做

| 顺序 | 具体工作 | 完成门槛 |
| --- | --- | --- |
| 已完成 | 0.3.0 发布核验和实际状态记录。 | 同一源码五个原生目标通过；八个目标包、校验文件和标签来源一致，交付结果已记录。 |
| 1 | 优先准备 OpenAI／Anthropic 的确切型号和受控替代。 | 核实官方访问、型号版本及可比设置；用户单独确认先导范围和请求／token 预算，Key 仅本机隐藏输入。未具备访问时只做离线准备。 |
| 2 | 执行并审阅先导。 | 保存全部成功、失败、未交卷和实际用量；按模板检查过易、过难、歧义、格式与强弱区分。不得只保留成功场次。 |
| 3 | 冻结正式实验，用独立新题跨日期验证。 | 对每个确切型号、配置和卷型独立报告误报、检出、无法判断、完卷率、复考波动、区间和开销。达到统计门槛后仍需独立审阅。 |
| 4 | 同标准推进 DeepSeek／Gemini，随后单独审阅上游集成。 | 不外推其他家族的实测结论；P0 缺陷修复继续优先。 |

真实研究的候选、完整请求量与默认建议见 [首批实测方案](CALIBRATION_PILOT_PLAN.md)。120／180 题分别研究；价格无可靠依据时保持未知。沿用误报率 95% 区间上界 ≤5%、完整弱替换检出率下界 ≥80% 的复核目标；当前没有型号达标证据。

## 5. 无 Key 的复现入口

在仓库根目录使用 Python 3.11+ 与 Node.js。以下只使用合成数据或离线逻辑，不需要官方 Key：

```text
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
python -I -S -B run.py suites
python -I -S -B run.py demo
python -I -S -B run.py calibration-simulate --trials 20 --seed 42
```

排查题目时优先运行 `test_native_exam_engine.py`、`test_gemini_exam_engine.py`；确认与预算看 `test_family_exam_binding.py`、`test_four_family_service.py`；研究证据看 `test_exam_calibration.py`、`test_calibration_metrics*.py`、`test_calibration_changed_effort.py`。完整检查及原生构建按[贡献指南](../CONTRIBUTING.md)和[发布流程](RELEASING.md)执行。手册内容变化后运行 `python -B build_tools/manual_docs.py`，再核对离线图片与生成的 Markdown。

## 6. Token 监视器接口与已知限制

未来集成在上游独立分支中进行，采用 [匿名 v2 接口](EXTENDING.md#integration-contract--token监视器接入)。主项目消费 `Auditor.snapshot()`、`Auditor.usage_snapshot()` 或本机受保护的快照，不接触检测专用 Key。官方登录只统计用量；业务、中转探针、官方参考与未知来源分组保持独立。主采集器继续离线、只读，不能以检测模块需要网络为由放宽其边界。

当前结果均为实验性：各家族的分数不是跨家族排名，能力差距不是型号身份认证或造假证明。真实精度、完整原生 GUI 人工验收仍待验证；Windows 未签名，macOS 未 Apple 公证。合成测试、打包冒烟和真实模型校准分别记录。

Windows 云端回归可能明显慢于本机：四家完整考试矩阵的单项包含 3,600 次合成请求和 7,256 次 SQLite 事务提交，2026-11-15 核验时本机约 23.9 秒、云端约 159 秒。遇到长时间运行先核对日志是否持续推进，再定位失败；不得通过删减题量、记账或质量断言使检查变绿。

## 7. 后续开发者如何续写进度

每完成一个可验收的工作单元，在 [WORKLOG](../WORKLOG.md) 追加日期、目标、涉及模块、完成结果、真实运行的检查、限制和下一步；检查的环境、命令和通过／失败／跳过数进入 [VERIFICATION](VERIFICATION.md)。用户可见变化同步 [CHANGELOG](../CHANGELOG.md)，范围和优先级变化同步 [路线图](DEVELOPMENT_PLAN.md)，再更新本页的当前阶段。

发布记录另写目标仓库、提交、Actions／Release 链接、资产及哈希核验、实际签名和平台验收状态。计划、软件通过、真实校准及公开发布要分别给出证据。日志使用合成复现和匿名汇总，不写模型 Key、私人地址、配置、原始答案或真实业务数据。
