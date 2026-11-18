# AgentChaos

[![CI](https://github.com/drashtimagia/agentchaos/actions/workflows/ci.yml/badge.svg)](https://github.com/drashtimagia/agentchaos/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentchaos)](https://pypi.org/project/agentchaos/)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)

**Chaos engineering for AI agents.** AgentChaos sits between an agent and its
tools, injects realistic failures — timeouts, rate limits, malformed responses,
stale data, schema drift — and measures how well the agent handles them.

No real network calls. No API key needed to run the built-in test suite.

---

## Install

```sh
pip install agentchaos                       # core + scripted runner
pip install 'agentchaos[claude]'             # + Claude Agent SDK runner
pip install 'agentchaos[openai]'             # + OpenAI Agents SDK runner
pip install 'agentchaos[langgraph]'          # + LangGraph ReAct runner
pip install 'agentchaos[otel]'              # + OpenTelemetry OTLP export
pip install 'agentchaos[pytest]'             # + pytest fixtures/marker
pip install 'agentchaos[claude,otel,pytest]' # all at once
```

Or with uv:

```sh
uv sync --all-extras
```

---

## Quick start

```sh
# No API key needed: a scripted agent that retries twice, then gives up.
agentchaos run --scenario inventory --profile flaky-network,stale-cache \
    --trials 20 --agent scripted

# A real agent (Claude Agent SDK). Needs ANTHROPIC_API_KEY.
agentchaos run --scenario bank_transfer --faults timeout,rate_limit \
    --trials 10 --agent claude:claude-opus-5-5
```

Each run prints a results table (success rate + 95 % CI, safety violations,
graceful-failure rate) and writes a JSONL trace to `results/`.

Reproduce any run from its trace:

```sh
agentchaos replay <run_id>
```

---

## Multi-framework bench

Compare agents across frameworks in one command:

```sh
agentchaos bench \
    --scenarios ticketing,bank_transfer \
    --agents "scripted,claude:claude-opus-5-5" \
    --profile flaky-network \
    --trials 25 \
    --report results/report.html \
    --ci                          # writes $GITHUB_STEP_SUMMARY
```

`--smoke` runs one trial per cell for fast CI preflight.
`--max-cost 2.00` aborts if the run would exceed $2 USD.
`--cache-dir ~/.cache/agentchaos` skips trials whose result is already on disk.

---

## Proxy any MCP server

The proxy mirrors an upstream MCP server's tools and injects faults
transparently. Point your agent's MCP config at it instead of the real server:

```json
{
  "mcpServers": {
    "tickets": {
      "command": "agentchaos",
      "args": ["proxy", "--profile", "flaky-network",
               "--upstream", "python -m my_ticket_server",
               "--trace", "/tmp/tickets.jsonl"]
    }
  }
}
```

`--upstream` takes a shell command (stdio) or an `http(s)://` URL.
Add `--transport http --port 8765` to serve the proxy over streamable HTTP.

```sh
agentchaos serve ticketing   # expose a built-in fake server for testing
```

---

## Policies

Policies are YAML ([schema](schemas/policy.v1.schema.json)):

```yaml
schema_version: 1
seed: 42
profile: rate-limited        # include a built-in profile's rules first
rules:
  - tools: "create_*"
    fault: timeout
    probability: 0.3
    params: {phase: after}   # the write happens, the agent is told it failed
```

```sh
agentchaos run --policy my-policy.yaml --trials 20
```

Built-in profiles: `uv run agentchaos profiles`
Built-in faults: `uv run agentchaos faults`

---

## Plain Python tools

```python
from agentchaos import Injector, chaos, load_policy


@chaos.tool
async def search(query: str) -> list[str]: ...


with chaos.activate(Injector(load_policy("policy.yaml"))):
    await search("open bugs")  # faults from the policy apply here
```

---

## pytest integration

```sh
pip install 'agentchaos[pytest]'
```

```python
import pytest
from agentchaos import chaos


@chaos.tool
async def call_api(endpoint: str) -> dict: ...


@pytest.mark.chaos(profile="flaky-network", seed=42)
async def test_agent_survives_flaky_network(chaos_injector):
    result = await call_api("/items")  # faults injected automatically
    assert result is not None


@pytest.mark.chaos(faults="timeout,rate_limit", probability=0.5)
async def test_agent_retries(chaos_injector): ...
```

The `chaos_injector` fixture activates the injector for the test and
deactivates it on teardown. The `chaos_policy` fixture gives you the
`PolicyConfig` to pass to `run_trial` / `run_experiment` directly.

---

## OpenTelemetry export

```sh
pip install 'agentchaos[otel]'
agentchaos export-otel results/my-run.jsonl --endpoint http://localhost:4317
```

Each run becomes a root span; each tool call a child span; each injected fault
an event on that span. Works with Jaeger, Grafana Tempo, Honeycomb, and any
OTLP-compatible backend.

---

## Write a fault plugin

```python
# my_package/my_fault.py
from dataclasses import dataclass, field
from agentchaos.core.faults import Fault, ToolCallContext, ToolFault


@dataclass
class SlowDB(Fault):
    delay_ms: int = 2000
    default_probability: float = field(default=0.15, init=False, repr=False)

    async def apply(self, ctx: ToolCallContext, call_next):
        if ctx.rng.random() >= self.default_probability:
            return await call_next(ctx)
        raise ToolFault(f"DB query timed out after {self.delay_ms} ms")
```

Register it as an entry point so AgentChaos discovers it automatically:

```toml
[project.entry-points."agentchaos.faults"]
slow_db = "my_package.my_fault:SlowDB"
```

See [`examples/slack_fault/`](examples/slack_fault/) for a complete example.

---

## Use as a GitHub Action

```yaml
- uses: drashtimagia/agentchaos@main
  with:
    scenarios: "ticketing,bank_transfer"
    agents: "scripted"
    profile: "flaky-network"
    trials: "20"
    smoke: "false"
```

The action installs agentchaos, runs the bench, uploads the HTML report as a
workflow artifact, and writes a markdown table to `$GITHUB_STEP_SUMMARY`.

---

## Development

```sh
uv run pytest -n auto
uv run ruff check . && uv run ruff format --check .
uv run pre-commit install
uv run agentchaos schema   # regenerate schemas/ after changing models
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide, including how to
write faults, scenarios, and runners. Design decisions are logged in
[DESIGN.md](DESIGN.md).

Licensed under [Apache 2.0](LICENSE).
