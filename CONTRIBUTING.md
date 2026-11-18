# Contributing to AgentChaos

Bug reports, feature requests, and pull requests are welcome.

## Dev setup

```sh
git clone https://github.com/drashtimagia/agentchaos.git
cd agentchaos
uv sync --all-extras          # installs every optional dep
uv run pre-commit install     # git hook: ruff on commit
```

Run the test suite:

```sh
uv run pytest -n auto         # parallel, all 145+ tests
uv run ruff check .           # lint
uv run ruff format --check .  # format check
```

No API key or network access is required — every test uses fake in-process
tool servers.

## Project layout

```
agentchaos/
  core/          # faults, models, policy engine, registry, recorder, decorator
  runners/       # agent adapters: scripted, claude, openai, langgraph
  scenarios/     # built-in task specs and fake MCP servers
  proxy/         # transparent MCP proxy (stdio + HTTP)
  cache.py       # trial-level response cache
  cli.py         # typer app
  ci_summary.py  # $GITHUB_STEP_SUMMARY writer
  otel.py        # OpenTelemetry OTLP export
  pytest_plugin.py
  report.py      # self-contained HTML report
examples/
  slack_fault/   # reference third-party fault plugin
schemas/         # JSON Schema for policy.v1
tests/
  test_phase1.py … test_phase4.py
```

## Writing a fault

A fault is a Python dataclass that extends `Fault` and lives in any
installable package. Register it via an entry point so AgentChaos discovers
it at runtime:

```toml
# your-package/pyproject.toml
[project.entry-points."agentchaos.faults"]
my_fault = "my_package:MyFault"
```

Minimal implementation:

```python
from dataclasses import dataclass, field
from agentchaos.core.faults import Fault, ToolCallContext, ToolFault


@dataclass
class MyFault(Fault):
    default_probability: float = field(default=0.2, init=False, repr=False)

    async def apply(self, ctx: ToolCallContext, call_next):
        if ctx.rng.random() >= self.default_probability:
            return await call_next(ctx)
        raise ToolFault("My fault fired")
```

See [`examples/slack_fault/`](examples/slack_fault/) for a complete example
with tests and a `pyproject.toml`.

## Writing a scenario

Extend `Scenario` in `agentchaos.scenarios.base`, register under
`agentchaos.scenarios`, and add a fake MCP server for the tools it needs.
Existing scenarios in `agentchaos/scenarios/tasks/` are the best reference.

## Pull request checklist

- [ ] `uv run pytest -n auto` passes
- [ ] `uv run ruff check . && uv run ruff format --check .` passes
- [ ] New faults/scenarios have at least one unit test
- [ ] No real network calls or API keys in tests

## Release process (maintainers only)

1. Bump `version` in `pyproject.toml` and `agentchaos/__init__.py` to match.
2. Push a tag: `git tag v0.x.y && git push origin v0.x.y`.
3. The [release workflow](.github/workflows/release.yml) builds the wheel and
   publishes to PyPI via Trusted Publisher — no token needed in the repo.
