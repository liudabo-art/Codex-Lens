# Relay Auditor

Codex Lens is an experimental relay model evaluation tool maintained in this independent repository. It originated as a Codex Token Usage Monitor module and retains the anonymous v2 contract for later integration. The desktop and CLI share one Python engine. The detector's own `VERSION` defines its release candidates.

Answer three questions: how does this relay perform on my tasks, has it changed against a reference or its own history, and what evidence/cost supports the conclusion? There is no model-authenticity score or public provider leaderboard. **No model has completed real calibration yet.**

## Desktop installation

See [installation and compatibility](../docs/INSTALLATION.md) for Windows, macOS and Linux. In the Windows source tree, double-click `启动桌面端.cmd` after building the local candidate. Closing stops future work. Issued requests may still be charged.

1. Import a CC Switch/Codex++ relay or add an API target. In the light workbench, select the target and the model it claims. To reuse the imported key after restart, opt in to saving the relay key in Windows Credential Manager. On a locked target you can paste a key and select **Start assessment** directly.
2. For an official comparison, open **Add official reference** on the target card, choose the official provider and region, enter its API key, and select **Save and match**. The tool fills in the endpoint and matches the declared model automatically. For example, relay `gpt5.6sol` matches OpenAI `gpt-5.6-sol`, while the relay still receives `gpt5.6sol`.
3. Read the request estimate and select **Start assessment**. The default screen runs 10 ability tasks. An eligible reference runs the same tasks for 20 requests total. When the screen observes a meaningful paired gap, you can preview and approve a separate run with fresh tasks. Dedicated behavior audits remain available under specialist controls.
4. Manual assessment and review wait for the protocol's completion signal. On an interrupted stream or connection error, the same question is retried up to twice on the failed side. The preview lists possible extra requests, and each retry counts toward the daily budget. Three failed attempts stop the run and preserve previous scores. Key, unsupported parameter and explicit output-limit errors stop immediately. Read the conclusion, observed scores and next step in the workbench, history or anonymous HTML.
5. To remove a target, open **⋯ → Delete detection target** and confirm. Stop that target's current run first. Successful deletion removes its local settings and dedicated saved keys, cancels its queued and periodic checks, and preserves recorded usage and anonymous reports. You can re-import it from the original manager configuration.

The 16 standard text API presets cover OpenAI, Anthropic, Google, DeepSeek, Qwen (Beijing, Singapore, Virginia and Hong Kong), GLM, Kimi and MiniMax (China and international for each), xAI and Mistral. Save and match checks model metadata where the endpoint supports discovery with the key alone. Qwen Beijing and Virginia, GLM and MiniMax use a versioned official catalog and leave key validation pending until the first assessment. Access to model metadata and permission to generate are separate. Saving a reference sends no test questions.

The declared model selects a GPT/Codex, DeepSeek, Claude or Gemini test profile independently of the wire protocol. Assessment v3 adds branching code and boundary repair tasks for GPT/Codex and multi-step constraints for DeepSeek. Other families use their existing tasks. Correctness and format compliance are recorded separately when a complete JSON answer can be recovered. Pairing requires an exact model ID or a verified provider alias, compatible request settings and the corresponding official provider. A provider or region change requires its own key. Existing reference keys remain pinned to their original provider. Dedicated behavior evidence remains experimental. Direct DeepSeek API assessment uses separate usage accounting. Official logins are for usage accounting and periodic checks are opt-in.

Nonsecret target names, addresses, models and settings persist in a dedicated **private settings file**. Relay and official keys are memory-only by default. Windows has separate opt-in save options in the target's own Credential Manager entry. macOS and Linux use session keys. After restart, each unsaved key needs to be entered again. Periodic switches and pending jobs stay off. Corrupt settings are preserved. Custom names stay private, and the tool reads original manager files without editing them.

## Source / CLI / SDK

Core source needs Python 3.11+, standard library only. From the repository root:

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

`demo` is offline synthetic oracle output, labeled as demonstration, with temporary data removed; it measures no real model. CLI endpoints/keys use hidden prompts, never command arguments; unsafe echo fallback is rejected. Source desktop uses an isolated environment with `requirements-desktop.txt`, then `python -B desktop.py` (omit `-S`). Local Windows builds use pinned `requirements-build.txt` and `python -B build_tools/build.py`; a fresh candidate is smoke-tested before the source launcher switches. No runtime downloads. [Python API and contribution guide](../docs/EXTENDING.md).

## Tasks, protocols and evidence

| Dimension | Available software | Boundary |
| --- | --- | --- |
| Quality | Randomized constraints, code tracing, boundary repair, structured output, virtual tool arguments | Deterministic local grading; no generated-code execution or native tool-call test |
| Behavior | Optional official fingerprint and interleaved distribution comparison | Deviation is not identity certification |
| Reliability | Returned/attempted requests, format/network failures, latency mean/P95 | Failures are separate from model quality |
| Stability | Same-condition history and descriptive decline signal | Different parameters/suites cannot rank; no calibrated drift guarantee |

Long-context specialist tests use multi-position four-hop retrieval at roughly 4K/16K/64K **characters**, recording actual prompt lengths. Reasoning compares identical low/high tasks and optional reference, without assuming high always wins. Seed/version/count are recorded for replay, without raw prompts/answers. Legacy v1 results remain unverified in schema v2 reports.

| Explicit protocol | Connect/basic assessment | Matching reference | Real calibration |
| --- | --- | --- | --- |
| OpenAI Responses / Chat Completions | Implemented, per-endpoint parameters may fail | Independent official key or exact recent numeric pack | Pending; GPT/Codex first priority |
| DeepSeek Chat | Experimental final-answer parsing and diagnostics | Independent DeepSeek key at its fixed official endpoint | Pending |
| Anthropic Messages | Experimental native text/stream adapter | Fixed Anthropic API with independent key | Pending, separate family validation required |
| Gemini native | Experimental native text/stream adapter | Fixed Google API with independent key | Pending, separate family validation required |

OpenAI-compatible other models may receive basic tasks without becoming “verified models.” Reasoning mappings are explicit and model-dependent; unsupported settings fail, never silently downgrade. Listing is a bounded returned subset, not an exhaustive catalog or identity proof. No bundled verified public baseline exists. Image/audio/full-agent evaluation and executing generated code are deferred.

Paired quality defaults to 40 valid pairs, exact one-sided McNemar and a ten-point loss threshold; daily cross-target nominal alpha is 0.01/[j(j+1)]. Missing/invalid comparisons remain incomplete. Experimental historical fingerprints need 12 samples and expire after seven days. Different reference conditions cannot compare; imported packs remain user history. Timing and token counts alone do not identify models. See [methods, controlled study commands, limits and research references](../docs/METHODS.md).

## Budget, attribution and privacy

Default daily UTC+8 shared limit is 100 requests/100K estimated tokens, including references and failed requests. Batches reserve before starting; unsent reservations release on cancel. Expired crash holds reclaim after about five minutes. Unknown consumption retains its estimate. Provider usage may be false; prices/token estimates are not billing ceilings. Raising budgets is an explicit action.

Official-login business, direct official API, relay business per anonymous provider, unknown route, relay probes and official references stay separate. `accounting.group_usage` requires request-level route/auth evidence. Current configuration/GPT names cannot establish historical ownership. The JSONL observer therefore leaves historical routing unknown. Manager request-ledger ingestion and cross-source deduplication remain future work; imported session totals cannot simply be added to JSONL totals.

CC Switch reads verified Codex provider schemas via temporary SQLite copies including WAL/SHM. Codex++ reads verified relayProfiles/configContents formats; other forks/versions may be unsupported. Auto-discovery tries fixed documented locations only; custom locations use file selection. No configured hooks, provider switches or login renewals execute. Original supplier names/IDs remain hidden.

Source data lives in ignored `.relay-data/`; desktop data lives under the current user's local application-data `Relay-Auditor` directory, with no automatic old-history migration. Anonymous `audit.sqlite` is separate from private `private/settings.json` and optional exact-owned OS vault items. Settings/backups are private; do not share them. Export goes to the dedicated exports folder, never overwrites originals, and removes names/addresses/keys/raw business content. Aggregate exports are still local private information, not automatically safe to publish.

Dedicated relay keys and synthetic probes go only to the selected HTTPS relay. An official reference key is sent to its selected fixed provider and regional endpoint for model discovery and paired tests. No official-login token reading, inherited proxies, redirects, telemetry, remote viewer assets or private uploads. Random-path loopback Host/Origin checks and desktop WebView restrictions remain. Closing/exit cannot retract issued calls. Parent offline collection and official synchronization are unchanged.

## Validation and roadmap

```powershell
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
```

Default CI uses synthetic fixtures only on Windows/Linux. Real API calibration is a separate explicitly budgeted task, never automatic in tests. Frozen studies include generator/transport checksums, independent pilot/new-day samples, healthy/substitution/reasoning/truncation/mixed controls and exact confidence intervals. Target FP upper bound ≤5% and full-substitution power lower bound ≥80% have **not been measured**. A statistical pass remains a review candidate, not an automatic registry promotion. No copied noncommercial code/data is bundled. [Implementation status and remaining gates](../docs/DEVELOPMENT_PLAN.md).

M1 real model results, M2 full native Windows end-to-end acceptance, per-family calibration, manager ledgers and parent integration remain open. Browser/synthetic checks cannot close those gates. No commits, merges, signing or public release occurred as part of this implementation.
