# AgentChaos

Chaos engineering for AI agents. AgentChaos sits between an agent and its tools,
injects realistic failures (timeouts, rate limits, malformed responses, stale
data, schema drift) and checks what the agent did about them by inspecting the
final state of the world.

Status: early development (Phase 2 of 5). Interfaces will change.

## Try it

```sh
uv sync --all-extras

# No API key needed: a scripted agent that retries twice, then gives up.
uv run agentchaos run --scenario inventory --profile flaky-network,stale-cache \
    --trials 20 --agent scripted

# A real agent (Claude Agent SDK). Needs ANTHROPIC_API_KEY.
uv run agentchaos run --scenario bank_transfer --faults timeout,rate_limit --trials 10 \
    --agent claude:claude-opus-5-5
```

Each run prints a table per fault class (success with a 95% CI, success
relative to the clean baseline, share of runs with a safety violation, share of
failed runs where the agent clearly said it failed) and writes a JSONL trace to
`results/`. Any run can be reproduced from its trace:

```sh
uv run agentchaos replay <run_id>
```

Scenarios: `ticketing`, `bank_transfer`, `search_summarize`, `file_edit`,
`inventory`. Faults: `uv run agentchaos faults`. Profiles: `uv run agentchaos profiles`.

## Put it in front of any MCP server

The proxy mirrors an upstream MCP server's tools and injects faults into tool
calls. Point your agent's MCP config at it instead of the real server:

```json
{
  "mcpServers": {
    "tickets": {
      "command": "uv",
      "args": ["run", "agentchaos", "proxy", "--profile", "flaky-network",
               "--upstream", "python -m my_ticket_server", "--trace", "/tmp/tickets.jsonl"]
    }
  }
}
```

`--upstream` takes a command (stdio) or an `http(s)://` URL. Add
`--transport http --port 8765` to serve the proxy over streamable HTTP instead.
`agentchaos serve <scenario>` exposes any built-in fake server over MCP, which
is a quick way to try the proxy.

## Policies

Policies are YAML ([schema](schemas/policy.v1.schema.json)):

```yaml
schema_version: 1
seed: 42
profile: rate-limited        # optional: include a built-in profile's rules first
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
from agentchaos import Injector, chaos, load_policy


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
uv run agentchaos schema   # after changing models: regenerate schemas/
```

Design decisions are logged in [DESIGN.md](DESIGN.md). Licensed under Apache 2.0.
