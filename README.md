# AgentChaos

Chaos engineering for AI agents. AgentChaos sits between an agent and its tools,
injects realistic failures (timeouts, rate limits, upstream outages) and checks
what the agent did about them by inspecting the final state of the world.

Status: early development (Phase 1 of 5). Interfaces will change.

## Try it

```sh
uv sync --all-extras

# No API key needed: a scripted agent that retries twice, then gives up.
uv run agentchaos run --scenario ticketing --faults timeout,rate_limit,fail_after \
    --trials 10 --agent scripted

# A real agent (Claude Agent SDK). Needs ANTHROPIC_API_KEY.
AGENTCHAOS_MODEL=claude-opus-5-5 uv run agentchaos run --scenario ticketing \
    --faults timeout,rate_limit,fail_after --trials 10
```

Custom policies are YAML (schema: [`schemas/policy.v1.schema.json`](schemas/policy.v1.schema.json)):

```yaml
schema_version: 1
seed: 42
rules:
  - tools: "create_*"
    fault: timeout
    probability: 0.3
    params: {phase: after}   # the write happens, the agent is told it didn't
```

```sh
uv run agentchaos run --policy my-policy.yaml --trials 20
```

## Plain Python tools

```python
from agentchaos import Injector, PolicyConfig, chaos, load_policy


@chaos.tool
async def search(query: str) -> list[str]: ...


with chaos.activate(Injector(load_policy("policy.yaml"))):
    await search("open bugs")  # faults from the policy apply here
```

## Development

```sh
uv run pytest -n auto
uv run ruff check . && uv run ruff format --check .
uv run pre-commit install
```

Licensed under Apache 2.0.
