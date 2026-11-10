# Security and privacy / 安全与隐私

Codex Lens keeps local configurations, source data, credentials and reports private. Development, tests and issue reproductions use synthetic data.

- Relay API keys are dedicated to the selected HTTPS relay. Independent official reference keys are bound to fixed provider and region endpoints. Only explicit model discovery and assessment actions, or user-enabled scheduling, can make those requests. Prompts are synthetic. A manual assessment can resend the same synthetic question to the same endpoint after a connection failure. Every attempt is subject to the daily budget.
- Manager and usage sources are read-only. The optional usage worker runs with an offline guard and returns aggregate usage and activity hints. Official account login credentials are outside the detector's access boundary.
- Target settings are local. Keys are held in memory by default. Windows offers explicit persistence in a target-owned Credential Manager entry. Reports and exports contain bounded anonymous aggregates.
- Desktop pages and API controls run through a random local session on loopback. Native application dependencies are prepared at build or installation time.

报告漏洞时请使用脱敏复现、版本和受影响的代码路径。请把凭据、私人配置、账单、业务正文、真实日志和本地报告保留在本机。
