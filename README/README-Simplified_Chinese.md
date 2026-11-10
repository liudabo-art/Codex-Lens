# 中转模型质量检测 · Relay Auditor

Codex Lens 是在本仓库独立开发的实验性中转检测工具，源自 Token Usage Monitor 检测模块，保留匿名 v2 契约供后续接入。桌面端与 CLI 共用 Python 核心，检测器的 `VERSION` 定义自己的发布候选版本。

回答三个问题：任务表现是否符合预期、相对可信参考或历史是否变化、证据和复核成本如何。没有真假总分或公开供应商排行榜。**当前没有完成真实校准的型号。**

## 桌面安装与日常流程

Windows、macOS 和 Linux 的包格式和依赖见[安装与兼容性](../docs/INSTALLATION.md)。在 Windows 源码目录中，可在本地构建后双击 `启动桌面端.cmd`。关闭停止后续工作，已发请求仍可能收费。

1. 从 CC Switch/Codex++ 导入中转或手动添加 API 目标，在浅色工作台选择当前目标和供应商声明的型号。希望重启后直接使用导入的 Key，可选择保存到 Windows 凭据库。已锁定的目标可贴入 Key 后直接点「开始检测」。
2. 要做官方对照，在卡片点击「补充官方参考」，选择官方供应商与站点，填写该站的官方 API Key，再点「保存并匹配」。工具自动选择官方接口并匹配同型号。例如，中转 `gpt5.6sol` 可匹配 OpenAI `gpt-5.6-sol`，中转请求仍使用 `gpt5.6sol`。
3. 查看预计请求数后点击「开始检测」。默认初筛测 10 道能力题，有可用的匹配参考时两边共 20 次请求。观察到值得复核的同题差距时，可预览并确认用一批新题复测。行为指纹可在专项设置单独运行。
4. 手动检测和复核会等待协议完成信号。断流或连接失败时，仅在失败一侧重试原题，最多两次。预览列出可能的额外请求，每次重试计入每日预算。同题连续三次失败会中止本轮并保留之前的成绩。Key 无效、参数不支持或明确达到输出上限时立即提示。工作台、历史详情和匿名 HTML 都可查看结论、观察成绩和下一步。
5. 在卡片「⋯ → 删除检测目标」中确认删除。该目标正在检测时，先停止本轮。删除成功后清理本工具里的配置与已保存 Key，取消排队及周期检测，保留匿名报告和已记录用量。之后可从原供应商配置重新导入。

标准文本 API 内置 16 个入口，覆盖 OpenAI、Anthropic、Google、DeepSeek、Qwen（北京、新加坡、美国弗吉尼亚、中国香港）、GLM、Kimi、MiniMax（各分中国站和国际站）、xAI 和 Mistral。能只凭 Key 查目录时，保存阶段先核对型号。Qwen 北京和美国弗吉尼亚、GLM 及 MiniMax 使用版本化官方型号表，Key 待首次检测验证。能查到型号与有权调用是两个条件。保存时只匹配，点击「开始检测」才发题。

声明型号独立于请求协议，决定采用 GPT/Codex、DeepSeek、Claude 或 Gemini 的哪套测试。评估 v3 为 GPT/Codex 加入多分支代码与边界修复题，为 DeepSeek 加入多步约束题。其他家族沿用现有题型。完整回答能提取 JSON 时，答题正确性与格式遵循分开记录。自动配对要求官方精确型号 ID 或已核实别名、可比的请求设置与对应官方供应商。换供应商或地区需要该站点的 Key，旧参考 Key 仍绑定原入口。专项行为证据处于实验阶段，型号结论待校准。DeepSeek 官方 API 直连用量单列，官方登录只做用量统计，周期检测由用户主动开启。

目标名称、地址、模型和设置保存在专用**私人配置文件**。中转 Key 和官方参考 Key 默认只留内存。Windows 可分别选择存入该目标专用凭据项，macOS 和 Linux 使用会话 Key。重启后，未保存的 Key 需分别补填，周期和排队任务关闭。损坏配置会保留。自定义名称留在私人设置，原供应商文件只读。

## 源码、CLI与SDK

核心需Python3.11+，仅标准库。在仓库根目录运行：

```powershell
python -I -S -B run.py serve
python -I -S -B run.py suites
python -I -S -B run.py demo
python -I -S -B run.py calibration-simulate --trials 1000 --seed 42
python -I -S -B run.py quality
python -I -S -B run.py profiles
python -I -S -B run.py estimate --target relay-1 --mode quality --samples 10
python -I -S -B run.py quality --target relay-1 --samples 10 --seed 42
python -I -S -B run.py quality-audit --target relay-1 --samples 40 --request-limit 1000 --token-limit 3000000
python -I -S -B run.py context --target relay-1 --samples 3
python -I -S -B run.py reasoning --target relay-1 --samples 5
python -I -S -B run.py history
```

`demo`离线使用已知答案模拟，明确标演示，临时数据退出删除，不代表真实模型成绩。CLI地址/Key隐藏输入，不接受命令行秘密；不能安全隐藏时拒绝回退。源码桌面需隔离环境安装`requirements-desktop.txt`，运行`python -B desktop.py`（勿加隐藏依赖的`-S`）。Windows构建用固定`requirements-build.txt`及`python -B build_tools/build.py`；新候选冒烟通过才切换启动器，不覆盖运行中的旧程序。运行时不下载依赖。见[Python接口与贡献指南](../docs/EXTENDING.md)。

## 检测任务、协议与证据

| 维度 | 已有软件能力 | 结论限制 |
| --- | --- | --- |
| 能力质量 | 随机约束、代码追踪、边界修复、结构输出、虚拟工具参数 | 本地确定性评分，不执行生成代码，不测原生工具调用 |
| 行为一致性 | 可选官方指纹、交错分布比较 | 偏离不认证身份 |
| 服务可靠性 | 返回/尝试次数、网络/格式失败、平均与P95延迟 | 服务失败与能力分别报告 |
| 长期稳定性 | 同条件历史和描述性下降线索 | 不同参数/任务不可排名，未校准漂移保证 |

长上下文专项为多位置四跳关联，约4K/16K/64K**字符**，保存实际提示长度，不宣称完整token窗口。推理专项同题比较low/high及可选参考，不假设高档总赢。报告保存种子/版本/题数以复算，不存正文/原始回答。旧v1结果在v2报告中继续标为未验证。

| 显式协议 | 连接/基础评测 | 匹配参考 | 真实校准 |
| --- | --- | --- | --- |
| OpenAI Responses / Chat Completions | 已实现，参数支持依端点而异 | 独立官方Key或精确近期数字参考 | 待完成，GPT/Codex优先 |
| DeepSeek Chat | 实验性最终答案解析和失败诊断 | 独立 DeepSeek Key，固定官方接口 | 待校准 |
| Anthropic Messages | 实验性原生文本/流式适配 | 独立Key、固定Anthropic官方API | 待完成，家族独立验证 |
| Gemini原生 | 实验性文本/流式适配 | 独立Key、固定Google官方API | 待完成，家族独立验证 |

其他OpenAI兼容模型可做基础题，不因此进入已验证名单。推理参数显式映射、支持依型号而异，不支持时报错，不静默降档。模型列表仅有界返回子集，不保证完整或真实身份。当前没有随包已验证公共基线。图像/音频/完整Agent评测、执行生成代码后置。

配对质量默认40对有效题、单侧精确McNemar、下降至少10个百分点；跨目标日内名义alpha为0.01/[j(j+1)]。缺失/无效保持不完整。实验历史指纹需12样本、7天过期。参考条件不匹配无法比较，导入参考仍标用户历史；响应速度和token数量不单独判断模型身份。见[方法、受控研究命令、边界与参考项目](../docs/METHODS.md)。

## 预算、归属与隐私

北京时间每日共享默认100请求/10万估算token，包括官方参考和失败尝试；启动前预留整批预算，取消释放未发请求。崩溃预留约5分钟过期可回收；未知消耗保留估算。供应商可能虚报用量，token和价格估算不是账单上限。提高预算是显式操作。

官方登录业务、官方API直连、各匿名中转供应商业务、未知路由、中转探针、官方参考分别计量。`accounting.group_usage`要求逐请求认证/路由证据。当前配置或GPT名称不能反推历史归属，因此JSONL观察仍保留未知。管理工具请求账本和跨来源去重待后续任务；导入会话汇总不能直接加到JSONL总数。

CC Switch支持已验证Codex供应商结构，只打开含WAL/SHM的临时SQLite副本；Codex++支持已验证relayProfiles/configContents结构，其他分支/版本不保证。自动读取只尝试固定文档位置，自定义用手选。不执行供应商切换、钩子或登录刷新，原供应商名称/ID不显示。

源码输出在忽略的`.relay-data/`，桌面在当前用户本地应用数据`Relay-Auditor`目录，不自动迁移旧历史。匿名`audit.sqlite`与私人`private/settings.json`、可选精确自有凭据项分开。私人配置/备份勿分享。导出只写专用exports目录，不覆盖原文件，排除私人名称、地址、Key和原始业务内容。匿名统计仍属私人本地信息，不自动视为可公开。

专用中转 Key 和合成题只到用户选择的 HTTPS 中转；官方参考 Key 只发往选定的固定官方站点，用于查询型号或发送对照题。不读官方登录 token，不继承代理、不重定向、不遥测、不加载远程页面资源、不上传私人数据。保留随机路径、Host/Origin 校验和 WebView 资源约束；退出不能撤回已发请求。主采集器保持离线，官方同步独立运行。

## 验证与后续门槛

```powershell
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
```

默认Windows/Linux CI只用合成数据。真实API校准独立授权预算，不混入普通测试。冻结研究含生成器/传输代码摘要、独立先导/新日期、正常/替换/档位/截断/混合控制与精确区间。误报上界≤5%、完整替换检出下界≥80%的目标**尚未实测**；统计通过也只成为复核候选，不自动升级名单。未打包非商业许可代码/数据。见[实施记录与未完成门槛](../docs/DEVELOPMENT_PLAN.md)。

M1真实研究结果、M2完整Windows原生端到端验收、各家族校准、管理工具账本及主监视器集成仍未完成；浏览器和合成检查不关闭这些门槛。本次不提交、合并、签名或公开发布。
