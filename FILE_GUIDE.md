# 文件与接口

| 部分 | 职责 |
| --- | --- |
| run.py / 启动中转检测.cmd | 独立源码入口 |
| 启动桌面端.cmd / desktop.py / relay_auditor/desktop.py | Windows 快捷入口、WebView2 / WKWebView / GTK 本机会话资源限制与服务生命周期 |
| desktop_actions.py / runtime.py | 原生选择、固定目录匿名导出、窗口提醒、专用数据目录与固定 worker 命令 |
| build_tools/ / requirements-*.txt / assets/ | 原生安装候选、固定依赖、应用图标、源码审阅包与合成冒烟 |
| VERSION / .github/workflows/ | 独立候选版本、推送时合成检查和手动原生构建矩阵 |
| protocol.py / statistics.py | 合成题、数字特征、固定批次分布检验、McNemar |
| core.py / __main__.py / cli.py | 桌面、CLI、Python共用的生命周期和API v2 |
| suites.py / quality.py | 版本化随机任务、确定性评分、质量/上下文/推理工作流 |
| families.py / assessment.py | 声明家族选题、同条件官方参考匹配、分项能力、同题重试和匿名失败归因 |
| reports.py / exporting.py / planning.py | 四维证据、v1兼容、同条件历史、离线HTML、预算/费用/支持矩阵 |
| profiles.py / vault.py / prompts.py | 私人配置、稳定目标编号、独立保存中转及官方 Key、按目标清理专用 Windows 凭据 |
| official.py / adapters.py | 16 个官方文本入口、型号目录和别名、对照请求参数、Anthropic/Gemini 原生文本与流式用量 |
| reference.py / calibration.py / calibration_cli.py | 严格数字参考包、用桌面检测引擎执行冻结研究、按题型汇总先导成绩、独立日期和验证区间 |
| simulation.py | 离线题量与缺失率模拟，使用合成结果验证配对判定与无参考历史趋势 |
| demo.py / docs/ | 离线合成演示、方法/贡献指南/实施门槛 |
| models.py | 有界配置/API模型ID列表过滤、自定义本地显示名验证 |
| transport.py | 内存凭据、API/SSE、固定官方参考、禁止代理继承/重定向 |
| storage.py / controller.py | 匿名过滤、预算/批次预留、审计编号、开关/调度/检测 |
| accounting.py | 请求证据归属、官方登录/各中转供应商分组契约 |
| catalog.py | CC Switch/Codex++ 目录读取，配置不当作历史消费 |
| observer.py / usage_worker.py | 固定离线子进程，只读 JSONL 输出匿名总量和活动线索 |
| vendor/sessions.py / vendor/safety.py | 主项目 0.2.0 同名源文件原样快照，独立运行，不动态导入父包 |
| server.py / web/ | 随机路径本机页面、设置、结果、历史、通知 |
| tests/ / README/ | 合成回归、完整双语文档 |
| .relay-data/ | 忽略的私人结果/预算/特征，绝不提交 |
| .venv/ / build/ / dist/ / release/ | 忽略的本地桌面开发构建与未发布便携包，不含真实源数据 |

## 接入契约 v2（兼容读取v1）

GET 随机会话路径的 `assessment` 对应 `Auditor.snapshot()`，返回匿名 schema v2 检测快照。`usage` 对应 `Auditor.usage_snapshot()`，返回独立用量快照。每结果含任务版本、合成种子和题数、证据等级及四维结果。POST estimate/run/cancel 提供预估、队列和取消。GET report 返回无脚本及远程资源的匿名 HTML。

桌面 state 另附非敏感 desktop 布尔能力标志（匿名持久导出过滤掉该 UI 字段）。POST desktop/catalog、desktop/observe、desktop/export、desktop/notifications、desktop/notify 仅在桌面宿主启用，沿用同源头/随机路径校验；没有传回私人路径的接口。浏览器模式这些路由返回404。桌面匿名数据库位于 `%LOCALAPPDATA%/Relay-Auditor`；导出只写其 exports 子目录。

state 附带实时 UI 使用的 display_names/model_choices/catalog_models/catalog_reasoning 映射及官方入口选项，匿名导出过滤 UI 字段。snapshot()/SQLite 不含自定义名称。POST models 可显式查询中转目录、目标或填写地址的 /models。POST target_options 更新名称、模型和推理档位，reasoning_effort 是可导出的公开检测参数。desktop/catalog 的 auto=true 只查固定位置，catalog_select 的 run_now=true 才立即发起一次筛查。

POST official_reference 接收 target_id、preset_id、api_key 及可选的 save_credentials。服务端按固定入口匹配官方同型号，使用可用的元数据查询或版本化官方型号表。POST target_delete 只接受本工具的 target_id，拒绝删除正在运行的目标，成功后清理该目标的本地配置和专用凭据，取消待执行任务，保留历史与用量。两个路由沿用随机会话路径与同源校验。

epoch_id 是工具生成的运行批次。启用私人配置时，relay-N 随目标跨重启保留，删除后编号递增且不会重用。未启用私人配置时，relay-N 只在当前运行有效。每次目录加载另生成 catalog_id，选择目录项需携带匹配的 catalog_id，防止刷新后别名复用选错目标。baseline_id 同样由工具生成，协议哈希只使用公开检测参数。

v2 使用随机生成的自有 target_id，历史比较按该 ID 与比较条件关联。私人配置 `private/settings.json` 保存该 ID、中转协议、官方入口及同型号匹配信息。中转 Key 与官方参考 Key 可分别存入目标自有的 Windows UUID 凭据项，默认仅留内存。恢复后未保存中转 Key 的目标锁定，周期和队列关闭。更完整的契约见 [EXTENDING](docs/EXTENDING.md)。

group_usage 输入每行包含 input/output、可选缓存/推理子集、purpose、source_evidence。只有 scope=request 的 auth_mode=chatgpt/api_key、destination=official/relay、仅内存 provider 关联键可以确定业务归属。输出 official_login、relay、relay_providers、official_api、unknown、probe、reference，不输出原始 provider 映射。

JSONL、管理工具代理账本、导入 session 记录和官方账号快照保持覆盖说明；请求关联不足时并列显示，不直接相加/相减。实际网络目标优先于“官方”名称、model、requires_openai_auth 或缓存登录。

## 上游依据（2026-11-02）

- [CC Switch schema](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/database/schema.rs)：当前只实现 providers 读取；proxy_request_logs/data_source/rollups 后续适配。
- [CC Switch 配置](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/5-faq/5.1-config-files.md)：直连/路由/聚合与登录共存。
- [Codex++ settings](https://github.com/superman2003/codexplusplus/blob/main/crates/codex-plus-core/src/settings.rs)：relayProfiles、activeRelayId、configContents、authContents、officialMixApiKey。
- [Codex++ 同步](https://github.com/superman2003/codexplusplus/blob/main/crates/codex-plus-data/src/provider_sync.rs)：历史 model_provider 可改写，不是不可变路由账本。
