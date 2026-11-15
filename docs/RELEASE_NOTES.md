# Codex Lens 0.3.0 · 四家完整检测 / Four-family experimental preview

0.3.0 补齐 Claude 与 Gemini 的独立 120／180 题考试，完善四家的参数匹配、考试确认和结果反馈，并增加可复算的校准研究证据。OpenAI／Anthropic 并列最高优先。**当前没有完成真实校准的型号，检测结果仍为实验性。** 公开状态、日期和实际可下载文件以 [v0.3.0 Release](https://github.com/liudabo-art/Codex-Lens/releases/tag/v0.3.0) 为准。

Version 0.3.0 adds independent Claude and Gemini exams, strengthens exact-model settings and exam approval, and makes research scores and failures auditable. OpenAI and Anthropic are co-P0. **No model has completed real calibration; findings remain experimental.** The GitHub Release records publication status, date and available assets.

## 本版变化 / Changes

| 变化 / Change | 用户和开发者可见的结果 / Result |
| --- | --- |
| 四家完整考试 / Four-family exams | GPT/Codex、Claude、DeepSeek、Gemini 均可选 120／180 题、单侧或匹配官方同题对照。五类能力、三档难度、每组合四种结构；每个必考侧全部完成才给最终成绩。 / All four families support complete relay-only or matched official exams with a balanced five-skill, three-tier blueprint. |
| 独立试卷与兼容 / Independent papers | Claude 使用 `claude-exam-v1`，Gemini 使用 `gemini-exam-v1`，各有题目蓝图和独立答案程序。GPT/DeepSeek 保持 `exam-v2` 原题、答案和种子映射。 / New family-specific papers do not change legacy GPT/DeepSeek papers or grades. |
| 边界题复核 / Boundary checks | 明确 Claude 负向切片追踪题的结束边界，正文与独立答案程序一致，固定试卷覆盖回归。 / Claude reverse-slice prompts explicitly state their stop boundary, with frozen regression cases. |
| 型号与参数 / Exact-model settings | 界面、官方匹配与传输共用已核实的型号／协议规则；未知型号仅开放默认设置，不支持的旧设置明确提示。 / Reviewed settings are shared across UI, reference matching and transport; no silent model or effort fallback. |
| 确认与反馈 / Approval and reports | 确认绑定完整试卷规格、双方型号和设置；排队开跑前再次检查。报告区分中转领先、同分、证据不足和明显落后，桌面、历史与 HTML 共用结论。 / Stale approval is rejected before requests; shared reports separate observed scores from supported conclusions. |
| 离线研究预览 / Offline research planning | `calibration-plan` 无需 Key，展示完整试验及研究阶段的请求／token、重试、待确认建议和预算缺口。 / Keyless planning never authorizes collection or silently reduces exam quality. |
| 逐题证据与诊断 / Pilot evidence | 冻结清单重建并校验题目种子、模板、难度、侧别、评分与请求总计；模板诊断显示有效配对、未知、格式失分和重试。 / Pilot diagnostics keep unknown evidence separate from incorrect answers and format losses. |
| 验证成绩与失败 / Validation scores and failures | 双侧匿名计数支持分先导／验证的完卷率、无法判断比例、成绩分布和样本标准差。固定失败类别保留侧别与题号；旧缺失保持未知。 / Checked aggregate counts make repeat-score spread and terminal failures auditable without storing raw answers. |
| 研究条件保护 / Study controls | 保存输出上限，拒绝采集参数与冻结条件冲突；推理变化研究拒绝不支持或已知等价的配置。 / Frozen source hashes remain strict, and no unsupported control is silently substituted. |

巡检仍默认 10 题，周期检测由用户开关和设置间隔，不会自动启动能力考试。考试每题失败侧最多重试两次，每侧额外额度为题量的 20%；单侧最多预留 144／216 次，对照 288／432 次。答错和完整格式失分继续作答；认证、参数、截断、预算、取消或重试耗尽导致未交卷时保留进度与用量，不给最终成绩。

The 10-question screen remains the low-cost monitoring option. Periodic checks never launch full exams. Retries preserve the original question and settings on the failed side, with at most two retries per item and a per-side 20% allowance. Incomplete exams retain progress and usage without final marks. Budgets remain user-confirmed; unknown prices remain unknown.

## 安装包 / Packages

五个目标架构的发布清单如下。完整发布需八个目标包和 `SHA256SUMS.txt`，各任务通过后才公开预发布。下载状态以 Release 的 Assets 为准。

The release inventory covers five architectures with eight packages and a combined checksum file. Publication waits for the configured native build and smoke gates; check the actual Release assets.

| 系统 / System | 文件名 / Asset |
| --- | --- |
| Windows 10/11 x64 | `Relay-Auditor-0.3.0-windows-x64-Setup.exe` · `Relay-Auditor-0.3.0-windows-x64-portable.zip` |
| macOS Intel x64 | `Relay-Auditor-0.3.0-macos-x64.dmg` |
| macOS Apple Silicon arm64 | `Relay-Auditor-0.3.0-macos-arm64.dmg` |
| Ubuntu 24.04 x64 | `Relay-Auditor-0.3.0-linux-x64.deb` · `Relay-Auditor-0.3.0-linux-x64.tar.gz` |
| Ubuntu 24.04 ARM64 | `Relay-Auditor-0.3.0-linux-arm64.deb` · `Relay-Auditor-0.3.0-linux-arm64.tar.gz` |

下载同一 Release 的 `SHA256SUMS.txt` 核对 SHA-256。Windows 未签名，需系统已有 WebView2 Runtime。macOS 构建目标为 13+，使用临时签名，未做 Apple 公证。Linux 需 GTK 3、WebKitGTK 4.1 和 glibc 2.39+。应用运行时不下载依赖。

Verify the selected package against `SHA256SUMS.txt` from the same Release. Windows packages are unsigned and require an existing WebView2 Runtime. macOS targets 13+ with ad hoc signing, without Apple notarization. Linux requires GTK 3, WebKitGTK 4.1 and glibc 2.39+. Runtime dependencies are not downloaded by the application.

## 升级与开发交接 / Upgrade and developer handoff

- **旧历史保留。** 不重算旧分数，不把旧实验结果提升为已校准。不同题集／型号／设置的分数不能直接排名。源码桌面与打包桌面在同一系统共用桌面数据目录；CLI 默认的 `.relay-data/` 不自动迁入。升级时关闭旧程序，完整解压或安装新版，不混用 `_internal` 与 worker 文件。
- **旧参数需确认。** 已保存但不受支持的推理设置会保留显示并提示调整；重新匹配官方参考、重新预览后再考试，不自动降档。
- **冻结研究需对应源码。** 本版增加源文件与证据校验。旧研究用原冻结源码复现；新源码初始化新研究，不改写旧清单来绕过哈希。旧记录缺少成绩或失败证据时明确显示不可用，不补零。
- **接入接口保持匿名 v2。** Token 监视器未来消费匿名快照；官方登录仅计量，中转探针和官方参考分别记账。检测 Key、地址、私人名称和原始回答不进入报告。

Existing history keeps its original suite version and marks. Reconfirm saved settings that are no longer supported instead of accepting a fallback. Reproduce frozen studies with the matching source, or initialize new studies; do not rewrite manifests to bypass hashes. Missing legacy evidence stays unknown. The anonymous v2 Token Monitor contract and separate login/probe/reference accounting remain intact.

## 验证与仍待完成的工作 / Verification and remaining work

软件验收使用合成数据，具体命令、测试数、平台构建及实际结果见[验证记录](VERIFICATION.md)。原生包、worker、资源和安装冒烟不等于完整原生 GUI 人工验收。四家型号的题目区分度、复考稳定性、误报率与检出率仍需单独授权官方访问、预算和跨日期真实采样。

Software checks use synthetic data; the verification record contains actual commands, counts and outcomes. Package and worker smoke checks do not replace full native GUI acceptance. Family/model-level discrimination, repeatability, false positives and detection power still require independently authorized real studies. Observed capability gaps do not establish model identity or fraud.

[持续更新的开发交接 / Developer handoff](https://github.com/liudabo-art/Codex-Lens/blob/main/docs/DEVELOPER_HANDOFF.md) · [工作进度 / Work log](https://github.com/liudabo-art/Codex-Lens/blob/main/WORKLOG.md) · [发布后核验 / Publication evidence](https://github.com/liudabo-art/Codex-Lens/blob/main/docs/VERIFICATION.md)。安装包复现使用下方版本标签，主分支的后续文档记录分别维护。 / Use the version tag below to reproduce packages; later progress documentation is maintained separately on main.

[安装指南 / Installation](https://github.com/liudabo-art/Codex-Lens/blob/v0.3.0/docs/INSTALLATION.md) · [操作手册 / Manual](https://github.com/liudabo-art/Codex-Lens/blob/v0.3.0/docs/USER_MANUAL.md) · [支持矩阵 / Support](https://github.com/liudabo-art/Codex-Lens/blob/v0.3.0/docs/FOUR_FAMILY_DETECTION.md) · [方法 / Methods](https://github.com/liudabo-art/Codex-Lens/blob/v0.3.0/docs/METHODS.md) · [验证 / Verification](https://github.com/liudabo-art/Codex-Lens/blob/v0.3.0/docs/VERIFICATION.md) · [源码 / Source](https://github.com/liudabo-art/Codex-Lens/tree/v0.3.0) · [0.2.0 历史说明 / Historical notes](https://github.com/liudabo-art/Codex-Lens/blob/v0.2.0/docs/RELEASE_NOTES.md)
