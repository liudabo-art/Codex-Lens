# Codex Lens 0.2.0 · 实验性桌面预览 / Experimental desktop preview

0.2.0 增加完整能力考试、共享评分器、匿名逐题证据、历史删除与离线图文手册。检测结果仍是实验性观察；当前没有完成真实校准的型号。公开状态、发布日期和可用资产以对应 [GitHub Release](https://github.com/liudabo-art/Codex-Lens/releases) 为准。

Version 0.2.0 adds complete capability exams, shared scoring, anonymous per-item evidence, history deletion and an illustrated offline manual. All findings remain experimental. No model has completed real calibration. The corresponding GitHub Release records publication status, date and available assets.

## 本版变化 / Changes

- **120／180 题能力考试。** GPT/Codex 与 DeepSeek 可选单侧或官方同型号同题对照，覆盖五类能力、三档难度。每个能力与难度组合含四种结构，每 60 题均衡抽取。所有必考侧交卷后才给总分；未交卷保留进度与用量。连接失败、断流或空回答只补原题失败侧，每题最多两次，每侧额外额度为卷长的五分之一。开考前预览并预留基础及重试预算：单侧最多 144／216 次，配对最多 288／432 次。
- **`exam-v2`／`assessment-v4` 共享评分。** 有界评分器从完整回复中恢复唯一 JSON 答案，区分内容答错、格式偏差与无法解析。多个候选、重复字段、超限或损坏输入有独立诊断。独立参考算法验证生成题的标准答案。匿名 `item_results` 仅含题型、模板、难度、种子、答题侧、评分标记和尝试次数，不包含题目正文、原始回答、凭据或私人目标信息。
- **稳定历史与删除。** 历史使用本地 UUID，可删单条、勾选项或全部记录，包括最近 200 条之外的记录。当前卡片及复核关联同步更新；用量、预算、目标设置和已登记参考保留。运行或排队期间先等待任务结束。
- **离线操作手册。** 窗口内提供 13 章、12 张实际界面合成截图。随包手册与 Markdown 手册从同一内容源生成，不加载远程资源。
- **请求兼容与校准工具。** 已有目标可调整输出上限，考试预览显示双方上限。修复考试题请求校验，并兼容被错标为流式的完整 JSON；真正中断的流仍不算完成。冻结研究与离线模拟支持两套新版题集及 GPT/Codex、DeepSeek，记录请求/重试计划、先导模板统计与验证区间。这些工具和合成测试不构成真实校准。

- **Complete 120/180-question exams.** GPT/Codex and DeepSeek support relay-only or matching official comparisons across five skills and three difficulty tiers. Each skill/tier has four structures, balanced per 60-question block. Final marks require every required side to submit; incomplete runs retain progress and usage. Connection failures, interrupted streams and empty replies retry the original question only on the failed side, at most twice per item and within a per-side allowance of one fifth of the paper size. Preflight reserves base requests and retries: up to 144/216 requests relay-only or 288/432 paired.
- **Shared `exam-v2`/`assessment-v4` scoring.** Bounded unique-JSON recovery separates wrong content, recoverable format deviations and unparseable answers, with diagnostics for ambiguous, duplicate-key, oversized and malformed input. Independent solvers verify generated answers. Anonymous `item_results` contain grading metadata only: task/template, difficulty, seed, side, outcome and attempts. Reports contain no question text, raw answers, credentials or private target details.
- **Stable history and deletion.** Local UUIDs support single, selected and all-record deletion beyond the latest 200. Current cards and review links update while accounting, budgets, target settings and registered references remain. Wait for active or queued work to finish before deleting history.
- **Offline illustrated manual.** The packaged manual has 13 chapters and 12 real interface screenshots using synthetic scenarios. It shares its content source with the Markdown manual and loads no remote assets.
- **Transport and calibration tooling.** Existing targets expose output caps in the exam preview. Exam requests pass transport validation, and complete JSON mislabeled as an event stream is accepted; genuinely interrupted streams remain incomplete. Frozen study tools and offline simulations support both new suites, GPT/Codex and DeepSeek with request/retry plans, pilot template statistics and validation intervals. Synthetic checks are not real calibration results.

## 安装包 / Packages

五个目标架构的完整发布清单如下。安装包是否已经公开以 Release 的 Assets 为准。

The complete release inventory covers five target architectures. Check the Release assets for availability.

| 系统 / System | 文件名 / Asset |
| --- | --- |
| Windows 10/11 x64 | `Relay-Auditor-0.2.0-windows-x64-Setup.exe` · `Relay-Auditor-0.2.0-windows-x64-portable.zip` |
| macOS Intel x64 | `Relay-Auditor-0.2.0-macos-x64.dmg` |
| macOS Apple Silicon arm64 | `Relay-Auditor-0.2.0-macos-arm64.dmg` |
| Ubuntu 24.04 x64 | `Relay-Auditor-0.2.0-linux-x64.deb` · `Relay-Auditor-0.2.0-linux-x64.tar.gz` |
| Ubuntu 24.04 ARM64 | `Relay-Auditor-0.2.0-linux-arm64.deb` · `Relay-Auditor-0.2.0-linux-arm64.tar.gz` |

下载同一 Release 的 `SHA256SUMS.txt` 核对 SHA-256。Windows 未签名，需系统已有 WebView2 Runtime。macOS 构建目标为 13+，使用临时签名，未做 Apple 公证。Linux 需 GTK 3、WebKitGTK 4.1 和 glibc 2.39+。原生 WebView 由系统提供，应用运行时不下载依赖。

Verify downloads against `SHA256SUMS.txt` from the same Release. Windows builds are unsigned and require an existing WebView2 Runtime. macOS targets 13+ and uses ad hoc signing without Apple notarization. Linux requires GTK 3, WebKitGTK 4.1 and glibc 2.39+. Native WebViews are system dependencies; the app does not download runtime dependencies.

## 升级与证据边界 / Upgrade and evidence limits

旧数据库补充稳定记录 ID；旧成绩继续保留原题集版本和原分数，不按新评分器重算。同一平台的源码桌面与打包桌面共用用户桌面数据目录；默认 CLI 使用仓库中的 `.relay-data/`，不会自动把该处历史迁移到桌面目录。升级前关闭旧程序，完整解压新版便携包，不混用 `_internal` 或 worker 文件。操作自己的数据前可在本机保留私人备份；不要把备份上传到问题反馈。

Existing databases receive stable record IDs; historical suite versions and grades are preserved without rescoring. Source and packaged desktop apps on the same platform share the user's desktop data directory. The CLI defaults to the repository's `.relay-data/`, whose history is not automatically migrated into the desktop directory. Close the old app and extract the entire new portable bundle without mixing `_internal` or worker files. Keep any backup local and private.

准备本说明时已有 263 项 Python 合成测试、22 项 Node 前端检查及本地 Windows x64 便携候选验证记录。五平台原生 CI 的结果以对应工作流为准。完整原生 GUI 验收仍待完成，不能由 worker、资源、浏览器或合成检查代替。型号级误报率、检出率与复考稳定性仍待独立授权的真实采样和复核；显著行为差异不能证明模型身份或造假。

At preparation, recorded checks comprise 263 synthetic Python tests, 22 Node dashboard checks and a local Windows x64 portable candidate. The corresponding workflow records the five native build outcomes. Full native GUI acceptance remains pending; worker, resource, browser and synthetic checks do not replace it. Model-level false-positive rates, detection rates and exam repeatability still require separately authorized real sampling and review. A significant behavioral difference does not establish model identity or fraud.

[安装指南 / Installation](https://github.com/liudabo-art/Codex-Lens/blob/v0.2.0/docs/INSTALLATION.md) · [操作手册 / Manual](https://github.com/liudabo-art/Codex-Lens/blob/v0.2.0/docs/USER_MANUAL.md) · [方法与校准 / Methods](https://github.com/liudabo-art/Codex-Lens/blob/v0.2.0/docs/METHODS.md) · [验证记录 / Verification](https://github.com/liudabo-art/Codex-Lens/blob/v0.2.0/docs/VERIFICATION.md) · [源码 / Source](https://github.com/liudabo-art/Codex-Lens/tree/v0.2.0) · [0.1.0 历史说明 / Historical notes](https://github.com/liudabo-art/Codex-Lens/blob/v0.1.0/docs/RELEASE_NOTES.md)
