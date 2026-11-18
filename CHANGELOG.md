# Changelog

All notable changes to AgentChaos are documented here.
Versions follow [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — 2026-11-18

First public release.

### Added

**Core fault engine**
- Eight built-in faults: `timeout`, `rate_limit`, `fail_after`, `error_mid_task`,
  `latency`, `malformed_json`, `stale_data`, `schema_drift`
- Deterministic per-call RNG seeded from `(seed, call_index, rule_index)` — runs
  are fully reproducible
- `@chaos.tool` decorator + `Injector` context manager for plain Python tools
- YAML policy files with glob-matched tool rules, built-in profiles
  (`flaky-network`, `rate-limited`, `stale-cache`, `adversarial`)
- Wilson-score 95 % confidence intervals on all rates
- Third-party fault discovery via `agentchaos.faults` entry points

**Runners**
- `scripted` — deterministic, no LLM or API key required
- `claude` — Claude Agent SDK runner (requires `ANTHROPIC_API_KEY`)
- `openai` — OpenAI Agents SDK runner
- `langgraph` — LangGraph ReAct runner

**Scenarios**
- Five built-in task scenarios: `ticketing`, `bank_transfer`,
  `search_summarize`, `file_edit`, `inventory`
- Each scenario ships a fake in-process MCP server — no real API calls in tests

**Transparent MCP proxy**
- Stdio and streamable HTTP transports
- Fault injection into any existing MCP server without modifying it
- `agentchaos serve <scenario>` exposes a built-in fake server over MCP

**Bench command**
- `agentchaos bench` — multi-agent, multi-scenario matrix with concurrent trials
- Trial-level `ResponseCache` keyed by `(agent, scenario, fault_class, seed, policy)`
- `--max-cost` guard aborts when cumulative LLM spend exceeds a budget
- `--smoke` mode for fast CI pre-flight (one trial per cell)

**Resilience scoring**
- Composite 0–100 score: `100 × (0.40·D + 0.35·S + 0.15·G + 0.10·E)`
- D = task-success rate, S = safety rate, G = graceful-failure rate,
  E = execution rate (no uncaught crashes)
- 95 % CI propagated through the linear combination
- Printed as a summary table at the end of `agentchaos bench`

**Reporting**
- Self-contained HTML report (no external CSS/JS)
- `$GITHUB_STEP_SUMMARY` markdown writer for CI dashboards

**pytest integration** (`agentchaos[pytest]`)
- `@pytest.mark.chaos(profile=, faults=, probability=, seed=)` marker
- `chaos_policy` fixture — `PolicyConfig` from marker params
- `chaos_injector` fixture — activates/deactivates around the test body
- Auto-registers via `pytest11` entry point

**OpenTelemetry export** (`agentchaos[otel]`)
- `agentchaos export-otel <trace.jsonl>` sends runs to any OTLP backend
- Run → root span, tool call → child span, fault → span event

**GitHub Action**
- `action.yml` composite action: install, bench, upload HTML artifact,
  write step summary

**Plugin system**
- `examples/slack_fault/` — reference third-party fault plugin
- Entry-point discovery for faults and scenarios

**Packaging**
- `py.typed` marker for mypy/pyright compatibility
- PyPI classifiers, keywords, project URLs
- `release.yml` — tag-triggered PyPI publish via Trusted Publisher
