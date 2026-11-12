# CLI / Python API / contributions

API version is **2** (`relay_auditor.core.API_VERSION`). The detector's `VERSION` identifies the desktop package. Work from the source checkout with Python 3.11+. The core uses only the standard library. 从源码使用，API 版本与安装包版本分别管理。

## Source CLI / 源码命令

Run from the root of the standalone repository. Endpoints/keys use non-echoing prompts, never command arguments. `--target relay-N` selects an already saved private target; obtain aliases with `profiles`. Keys are re-entered if not explicitly saved with `--save-key` on Windows. Estimates for saved targets are offline and do not require unlocking keys. A terminal unable to hide input is rejected rather than echoing secrets.

在独立仓库根目录运行。地址/Key只接受隐藏输入，不放命令行。`profiles`列匿名目标；`--target`选择已有配置，未保存Key则补填。保存目标的`estimate`不联网、不要求解锁。

```powershell
python -I -S -B run.py --help
python -I -S -B run.py suites
python -I -S -B run.py demo
python -I -S -B run.py profiles
python -I -S -B run.py estimate --target relay-1 --mode quality --samples 10
python -I -S -B run.py quality --target relay-1 --samples 10 --seed 42
python -I -S -B run.py quality-audit --target relay-1 --samples 40 --request-limit 1000 --token-limit 3000000
python -I -S -B run.py context --target relay-1 --samples 3
python -I -S -B run.py reasoning --target relay-1 --samples 5
python -I -S -B run.py support
python -I -S -B run.py history
```

`demo` is entirely offline, uses known synthetic oracle responses, labels them as demonstrations, and deletes its temporary database. It does not measure a real model. Other run commands spend API credit only after configuring/unlocking the chosen target. `serve` starts the same local UI; saved periodic switches and queues never resume after restart.

`demo`为离线模拟，使用已知答案且显式标演示，临时数据退出删除，不代表真实模型成绩。其他检测命令会调用用户配置的接口；`serve`启动同一界面，重启不恢复付费工作。

## Python owner and reproducible tasks / Python核心与任务复算

```python
from relay_auditor.core import Auditor, API_VERSION
from relay_auditor.suites import cases
from relay_auditor.protocol import Protocol

# Offline replay of a report's procedural questions and deterministic scores:
for case in cases('quality', 10, seed=42):
    assert case.grade('{"answer":null}')['correct'] is False

# Set directory and secrets privately in your embedding application.
# persist_settings defaults False; no OS vault is accessed by default.
with Auditor(private_directory) as auditor:
    alias = auditor.configure(relay_url, relay_key, model_id, Protocol())
    plan = auditor.estimate(alias, 'quality', 10)
    # Run only following explicit user action and accepted budget:
    # result = auditor.run(alias, 'quality', 10, seed=42)
    # job_id = auditor.submit(alias, 'quality', 10, seed=42)
    # auditor.cancel(job_id)
    snapshot = auditor.snapshot()
    usage = auditor.usage_snapshot()
```

`client_factory` injection accepts a callable `(Target) -> client` implementing `complete(ProbeCase) -> Completion` and `list_models() -> list[str]`. Synthetic tests use this boundary without HTTP. Core owns the Store and Service; closing cancels unsent work and closes the store after an in-flight call settles. Embedders must honor opt-in, fixed official reference boundaries, output privacy and no arbitrary code execution.

SDK默认不保存配置/不访问凭据库。`client_factory`可注入模拟客户端。关闭取消后续请求，已发请求结算后关闭数据库；宿主继续遵循用户开关、官方参考和隐私边界。

`ReferencePack.load(path)` accepts bounded numeric packs only. `pack.install(store, target, reference_model)` rejects mismatched/stale packs and records `user_history`. There is no automatic remote baseline download or trusted promotion. The constructor is for reviewed in-process numeric features, not arbitrary untrusted dictionaries.

## Capability Exam / 能力考试

`capability-exam` is the manual CLI command for `capability_exam`. It accepts `--samples 120` or `--samples 180`. Set an explicit daily budget and pass `--confirm-exam` with `--comparison relay_only` or `--comparison paired` to start. `estimate --mode capability_exam` shows the current estimate without sending test requests.

`--max-output-tokens 8192` sets the output cap for a new target or explicitly updates the selected `--target`; the supported range is 128–16384. Omitting it preserves the selected target's saved cap. Existing desktop targets expose the same setting under advanced test settings. Cap changes invalidate previous exam approval and may require rematching a named official reference. Exam previews include `max_output_tokens` and `reference_max_output_tokens` for the chosen sides. The local `target_options` route and `Service.update_target` accept optional `max_output_tokens`; omission preserves the current cap.

```powershell
python -I -S -B run.py estimate --target relay-1 --mode capability_exam --samples 120 --comparison relay_only
```

For the Python or loopback API, call `estimate(alias, 'capability_exam', samples, comparison='relay_only')` or send the same inputs to POST `estimate`. After explicit budget approval, pass the returned `exam_plan_id` to `run` or `submit`, or to POST `run`. A stale preview requires a new estimate. The identifier is scoped to confirmation and is excluded from anonymous reports. `required_requests` counts the base questions across the active sides. `max_requests` and `estimated_tokens` cover the reservation, including the retry allowance.

Python 或本机接口通过 `estimate` 选择卷型和对照方式，确认日预算后将 `exam_plan_id` 传给运行接口。确认凭据不随报告导出。匿名 v2 中的可选 `exam` 包含 `comparison`、`submitted`、`sides` 和 `sections`。卷型使用 `task_count` 区分，`task_seed` 与 `suite_version` 支持复现。仅 `submitted` 为真时展示总分。试卷生成器可在本地调用 `exam_cases(family, samples, seed)`。考试和巡检分别展示历史。

## Adding a task or provider / 社区贡献

1. Add an original procedural generator and deterministic oracle in `suites.py`, or a separate reviewed module imported there. Use bounded seeds/lengths and exact grading; never eval/exec a response, call external tools or download runtime assets. Include no private conversations or NC-licensed data. Add a new suite version when prompts, oracle, parser or task distribution change.
2. Register its immutable metadata in `SUITES` and route the job through `quality.py`/the controller. Every call must use `_call` and a batch reservation, cancellation and fixed error codes. Keep reference and relay usage separate. Publish synthetic seeds, expected failure cases and budget formula.
3. For a protocol, update `Protocol`, explicit `OFFICIAL_ENDPOINTS`, `transport.py`/`adapters.py`, effort mapping and discovery. Test request auth destinations, partial SSE usage, finish markers, truncation, unsupported parameters and failure settlement. Never inherit proxies, redirect credentials or silently change model/effort/protocol. Bump adapter version when comparison conditions change. No arbitrary dynamic plugin loading is enabled.
4. Add synthetic regressions with meaningful healthy/weak/unknown/missing cases and privacy checks. Ordinary CI never calls real APIs. Update both READMEs, support claims, method limits, file guide, changelog and worklog. Only an independently reviewed, separately authorized real study can add a calibrated model; passing software checks is insufficient.

新增任务/协议需要源码审阅与版本变更，不自动加载可执行插件。任务必须可复现、确定性评分、预算有界、失败保留；原生流式完整性、来源区分和凭据保护必须通过合成验收。真实模型研究单独预算授权，不能混入CI。

## Integration contract / Token监视器接入

Codex Lens is a detector module of Codex Token Usage Monitor. A future extension can consume v2 through `Auditor.snapshot()` and `Auditor.usage_snapshot()`, or through the locally launched service's `GET assessment` and `GET usage` session routes. Both pairs return aggregate JSON. The local `GET state` route is for the detector UI and contains private display names. Keep its random session URL in memory and use only the aggregate routes for host reports.

The host can use `Auditor.estimate()` before explicit approval of a job, `submit()` to queue it and `cancel()` to stop future requests. The module retains ownership of credentials, budgets, scheduling and the guarded usage worker. `target_id` and `job_id` are module-owned UUIDs. `protocol_id` binds test settings. A host should check `schema_version` and `snapshot_type` before importing a snapshot. V1 results remain legacy, even after reserialization.

Assessment v3 adds optional anonymous fields within snapshot schema v2. The plan includes `target_requests` and `reference_requests`. Results can carry `reference_comparison_conditions` and `paired_result.planned_pairs`. `loss_bounds` holds lower and upper proportions for the official-minus-target gap under missing scores. The UI-only `history_reports` maps by index to `history` within the same `state` response. Host callers use the existing structured `assessment` and `usage` snapshots.

For manual assessments, `max_retry_requests` is an additional request ceiling. `required_requests` and `estimated_tokens` cover the base run. `retry_requests` records extra attempts in the result and in the relevant side's counts. Interrupted manual runs can carry `failure_source` and `error_code` with retained scores.

主项目将来接入时，可调用 Python 接口或本机随机会话内的 `GET assessment` 和 `GET usage`，分别读取匿名检测和用量快照。先校验 `schema_version` 与 `snapshot_type`。界面专用 `state` 含私人显示名称，应留在模块内部。`target_id` 是模块生成的目标 ID。官方登录、官方 API、各中转供应商和未知来源分开处理，业务、探针和官方参考用量也分别保留。历史账本归属与去重需要逐请求证据。

## History and research APIs / 历史与研究接口

### History identity and deletion / 历史标识与删除

Every stored result receives a stable UUID `record_id`, including atomic migration of old records. `history_count` is the whole database count, while snapshots retain the latest 200 entries. POST `history_delete` accepts exactly one of `{"record_ids":["UUID"]}` or `{"all":true}` and returns `deleted_count` and `total_remaining`. Completed records can be deleted when no detection is running or queued. Requests with malformed IDs fail atomically. Deletion preserves usage, budgets, audit indices, credentials, settings and reference baselines. A retained follow-up view can carry `review_source_deleted`. Existing report scores are preserved.

`item_results` is optional anonymous v2 metadata. Each entry has `question_number`, `task_kind`, `template`, `difficulty`, `seed`, `source_kind`, `correct`, `format_state`, `attempts`, `error_code` and `grading_issue`. Template and diagnostic strings are allowlisted. Raw answers and prompts are excluded. `exam-v2` and `assessment-v4` coexist with original historical versions.

### Exam studies / 考试研究

`calibration-init` and `calibration-simulate` accept `--suite exam-v2|assessment-v4` and `--family gpt|deepseek`. Exam studies accept 120 or 180 samples and freeze model IDs, official preset, settings, source hashes, scoring, retry limits and independent dates/seeds. `calibration-collect` retains explicit request/token authorization and hidden official Key input. Normal tests and simulation use synthetic completions. Changing frozen implementation or conditions requires a new study.

```powershell
python -I -S -B run.py calibration-simulate --suite exam-v2 --family gpt --samples 120 --trials 10
```

The offline manual is authored in `relay_auditor/web/manual/content.json`. Run `python -B build_tools/manual_docs.py` after changing content to regenerate `docs/USER_MANUAL.md`. Fixed same-origin PNG routes and the source package list must match the manual manifest.

## Checks / 检查

```powershell
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
python -I -S -B run.py demo
```

See [native candidate builds](RELEASING.md). The manual workflow runs synthetic checks and builds platform-specific artifacts for review.
