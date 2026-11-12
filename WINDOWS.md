# Windows 桌面版 / Windows desktop

如使用便携 ZIP，请整体解压，双击 **Relay-Auditor.exe**，并保留同目录的 `_internal` 与 `Relay-Auditor-Worker.exe`。如使用 Setup，安装完成后从开始菜单打开 **Codex Lens**。支持 Windows 10/11 x64，系统需要已有 Microsoft Edge WebView2 Runtime，无需安装 Python。

Extract the complete portable ZIP and run **Relay-Auditor.exe**. Keep `_internal` and the fixed worker beside it. Python is bundled. Windows 10/11 x64 with an existing Microsoft Edge WebView2 Runtime is required; no runtime downloads or elevation.

本文适用于 0.2.0 未签名的实验性桌面预览，系统可能提示未知发布者。下载与公开状态见 [GitHub Releases](https://github.com/liudabo-art/Codex-Lens/releases)。模型行为和能力检测仍待真实校准，完整原生 GUI 验收也尚未完成。

This guide covers the unsigned 0.2.0 experimental desktop preview. Windows may warn about an unknown publisher. GitHub Releases records downloads and publication status. Real model calibration and full native GUI acceptance remain pending.

- 检测默认关闭。选择 CC Switch / Codex++，点击“一键读取供应商配置”；自定义位置用“手动选择配置文件”。修复了旧版过滤格式错误导致选择窗口打不开的问题，按钮附近会显示进度/错误。
- 从下拉列表选择模型并填写测试名称，点“导入目标”，然后点目标卡片上的“开始检测”。周期检测默认关闭，官方登录只做用量统计。
- 手动添加中转时填写地址/专用Key，点击“读取中转模型列表”后选择模型。列表来自配置或供应商 /models，不能证明真实身份；接口不支持查询时使用配置中的模型。推理档位支持模型默认、none/minimal/low/medium/high/xhigh/max；支持范围由模型/供应商决定，参数不支持时不静默降档。
- 每个目标可开关周期检测、调整间隔，默认关闭，默认间隔 15 分钟。名称、地址和设置保存在私人配置。中转 Key 和官方参考 Key 默认只留内存，可分别存入该目标专用的 Windows 凭据项。导入时可选保存中转 Key。旧卡重启后如需补 Key，贴入后可直接点「开始检测」。重启后周期和队列关闭。
- 在目标卡片点「补充官方参考」，选择官方供应商与站点，填写该站的官方 API Key，点击「保存并匹配」。工具自动核对同型号。例如，中转 `gpt5.6sol` 会匹配 OpenAI `gpt-5.6-sol`。保存只做匹配与可用的型号元数据查询。使用内置型号表的站点首次检测时才验证 Key。换站点时填写该站的官方 Key 即可。
- 从目标卡的「⋯ → 删除检测目标」清理本工具的配置和已保存 Key。目标正在检测时，先点「停止本轮检测」。删除成功会取消该目标的排队和周期检测，保留匿名历史和用量。之后可从原管理工具重新导入。
- 窗口提醒为可选任务栏闪烁，不添加托盘常驻/开机启动。关闭窗口停止后续检测与用量观察，已发请求可能收费。
- 统计/预算/匿名结果保存在当前用户本地应用数据的 `Relay-Auditor` 专用目录，源码桌面与打包桌面共用。导出按钮写入其 `exports` 子目录并打开文件夹。CLI 默认使用仓库中的 `.relay-data/`，不会自动迁移该处历史。
- 自动读取仅尝试固定常见位置，不递归扫描或修改原文件，不读取官方登录 token。自定义测试名可在私人设置保存，匿名导出/历史不保存它。当前用量观察仍将缺乏逐请求路由证据的历史保留为未知。
- 浅色工作台通过顶部下拉列表切换目标，报告将中转与官方成绩并排展示。开始前显示预计请求数，默认 10 道题，配对共 20 次请求。观察到值得复核的差距后，可先看额外请求量，再确认用新题复测。报告分列答对、答错、无法评分和有效同题差距。参考失配或权限不足时，仍可做中转单侧能力检测。DeepSeek 官方直连使用单独的统计分组。测试方案和官方对照仍处于实验阶段。
- GPT/Codex 和 DeepSeek 可手动运行 120／180 题能力考试。预览包含双方型号、推理和输出上限，先确认足够日预算；默认 100 请求额度不足整场考试。只在失败侧重试原题，每题最多两次，并受整卷重试额度约束。所有必考侧交卷后才给总分，未交卷保留进度和用量。
- `exam-v2`／`assessment-v4` 共用有界的唯一 JSON 恢复评分器。匿名逐题证据只保存模板、种子、状态与尝试次数等元数据，不保存题目正文或原始回答；旧成绩保留原版本和原分数。
- 历史支持单条、勾选或全部删除，保留用量、预算、目标设置和已登记参考；运行或排队时先等待结束。左侧「操作手册」可离线阅读 13 章、12 图教程，图片为实际界面合成场景。

Detection is off by default, with a user-controlled interval. Official login is used for usage accounting. Nonsecret settings persist privately. Relay and reference keys default to memory, and each has an optional save setting for the target's own Windows vault entry. Restart disables periodic work and queues, and any unsaved key needs to be entered again. Closing the window stops future work, and issued requests may still be charged. The optional taskbar flash needs no tray process or startup task. Anonymous data and exports stay in the current user's dedicated local application-data directory, shared by source and packaged desktop apps. Unknown historical routing remains unknown. The CLI defaults to the repository's `.relay-data/`; its history is not migrated into the desktop directory automatically.

Choose the manager and auto-read its known configuration location, or select a custom file. Pick a model from configuration or an explicitly requested relay model list and enter a private test name. For an official comparison, open **Add official reference** on the target card, choose the provider and region, enter that site's API key and select **Save and match**. The tool matches the same model automatically, such as relay `gpt5.6sol` to OpenAI `gpt-5.6-sol`. Saving checks the catalog or model metadata. Presets that use a bundled catalog validate the key on the first assessment. Changing the provider or region requires the key for the new site.

Check the request estimate and select **Start assessment** on the target card. The result leads with capability, the gap from an eligible official reference and reasons for unscored responses. Evidence details show both requested models and the comparison statistics. The relay-only assessment is available when the official reference cannot be used. Direct DeepSeek assessment uses a separate usage group. Test profiles and official comparisons are experimental and await real calibration.

Choose **⋯ → Delete detection target** on the card to remove its local settings and saved keys. Stop the target's current run first. Successful deletion cancels its queued and periodic checks, preserves anonymous reports and recorded usage, and leaves the original manager configuration available for re-import.

Quality, paired quality, context and reasoning jobs use preflight estimates and a cancellable queue. Four-dimensional evidence, history comparison and JSON/offline HTML exports are included. Native Claude/Gemini adapters remain experimental; no calibrated model claim is made.

手动检测和复核遇到断流或连接失败时，在失败侧重试原题，最多两次。若仍失败则弹出中止提示，已完成的题目保留。预算预览包含额外重试提示。更多说明见[双语使用文档](README.md)。

Manual assessment and review retry interrupted questions on the affected side up to twice, subject to the daily budget. If all attempts fail, the dialog explains the interruption and the report preserves earlier results. See the [English guide](README/README.md).

GPT/Codex and DeepSeek support manual 120/180-question exams. Preview both models, reasoning and output caps, then confirm sufficient daily budget; the default 100-request limit cannot cover a full exam. Retries target the original failed side and are limited per item and per paper. Final marks require every required side to submit; incomplete runs retain progress and usage. Shared `exam-v2`/`assessment-v4` scoring provides anonymous per-item grading metadata without question text or raw answers. Historical grades retain their original version and marks.

History supports single, selected and all-record deletion while preserving accounting, budgets, target settings and registered references. Wait for active or queued work to finish. The sidebar's **Operation Manual** offers 13 offline chapters and 12 screenshots of actual synthetic interface scenarios. Close the old version before upgrading and extract the new portable bundle in full. See the [0.2.0 release notes](docs/RELEASE_NOTES.md) and [illustrated manual](docs/USER_MANUAL.md).
