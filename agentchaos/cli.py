"""``agentchaos`` command-line interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentchaos.core import registry
from agentchaos.core.models import PolicyConfig
from agentchaos.core.policy import load_policy
from agentchaos.execution import CLEAN, policy_for, run_experiment
from agentchaos.scoring.score import summarize

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def run(
    scenario: Annotated[str, typer.Option(help="Scenario name.")] = "ticketing",
    faults: Annotated[str, typer.Option(help="Comma-separated fault classes.")] = "timeout",
    trials: Annotated[int, typer.Option(min=1, help="Runs per fault class.")] = 10,
    seed: Annotated[int, typer.Option(help="Base seed.")] = 0,
    agent: Annotated[str, typer.Option(help="'claude' or 'scripted' (no LLM).")] = "claude",
    model: Annotated[str | None, typer.Option(help="Overrides AGENTCHAOS_MODEL.")] = None,
    probability: Annotated[float | None, typer.Option(min=0, max=1)] = None,
    policy: Annotated[Path | None, typer.Option(help="Policy YAML; replaces --faults.")] = None,
    concurrency: Annotated[int, typer.Option(min=1)] = 4,
) -> None:
    """Run a scenario clean and under each fault class, then print a results table."""
    scen = registry.get_scenario(scenario)()
    policies: dict[str, PolicyConfig] = {CLEAN: PolicyConfig()}
    if policy:
        policies[policy.stem] = load_policy(policy)
    else:
        for f in filter(None, (s.strip() for s in faults.split(","))):
            policies[f] = policy_for(f, probability)

    if agent == "scripted":
        from agentchaos.runners.scripted import ScriptedAgent

        def factory():
            return ScriptedAgent(scen.reference_plan())
    elif agent == "claude":
        from agentchaos.runners.claude_agent import ClaudeAgentRunner

        def factory():
            return ClaudeAgentRunner(model=model)
    else:
        raise typer.BadParameter(f"unknown agent '{agent}'", param_hint="--agent")

    runs = asyncio.run(
        run_experiment(
            scen, factory, policies, trials=trials, base_seed=seed, concurrency=concurrency
        )
    )
    errors = [r for r in runs if r.outcome.agent_error]
    table = Table(title=f"{scenario} · {runs[0].agent} · {trials} trials/class · seed {seed}")
    for col in ("fault class", "success", "95% CI", "vs clean", "unsafe", "calls", "faults"):
        table.add_column(col, justify="left" if col == "fault class" else "right", no_wrap=True)
    for s in summarize(runs):
        lo, hi = s.success_ci
        table.add_row(
            s.fault_class,
            f"{s.successes}/{s.n} ({s.success_rate:.0%})",
            f"{lo:.0%}-{hi:.0%}",
            "—" if s.degradation is None else f"{s.degradation:.2f}",
            f"{s.safety_violation_rate:.0%}",
            f"{s.mean_calls:.1f}",
            f"{s.mean_faults:.1f}",
        )
    console.print(table)
    if errors:
        console.print(
            f"[yellow]{len(errors)} run(s) crashed. First: {errors[0].outcome.agent_error}"
        )


@app.command("faults")
def list_faults() -> None:
    """List registered faults (built-in and plugins)."""
    for name, cls in sorted(registry.faults().items()):
        console.print(f"{name:12} {cls.__module__}.{cls.__qualname__}")


@app.command()
def schema(out: Annotated[Path, typer.Option()] = Path("schemas")) -> None:
    """Regenerate published JSON Schemas."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "policy.v1.schema.json"
    path.write_text(json.dumps(PolicyConfig.model_json_schema(), indent=2) + "\n")
    console.print(f"wrote {path}")


if __name__ == "__main__":  # pragma: no cover
    app()
