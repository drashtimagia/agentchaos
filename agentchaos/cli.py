"""``agentchaos`` command-line interface."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import TypeAdapter
from rich.console import Console
from rich.table import Table

from agentchaos.core import registry
from agentchaos.core.models import PolicyConfig, Run, RunStart, TraceRecord
from agentchaos.core.policy import load_policy, profiles
from agentchaos.core.recorder import Recorder, find_run
from agentchaos.execution import CLEAN, policy_for, replay, run_experiment
from agentchaos.runners import make_agent
from agentchaos.scoring.oracles import ClaudeJudge, Judge, KeywordJudge
from agentchaos.scoring.score import summarize

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
err = Console(stderr=True)  # stdout belongs to the MCP protocol in stdio mode

Transport = Annotated[str, typer.Option(help="'stdio' or 'http'.")]


@app.command()
def run(
    scenario: Annotated[str, typer.Option(help="Scenario name.")] = "ticketing",
    faults: Annotated[str, typer.Option(help="Comma-separated fault classes.")] = "",
    profile: Annotated[str, typer.Option(help="Comma-separated profiles.")] = "",
    policy: Annotated[Path | None, typer.Option(help="Policy YAML, run as one class.")] = None,
    trials: Annotated[int, typer.Option(min=1, help="Runs per class.")] = 10,
    seed: Annotated[int, typer.Option(help="Base seed.")] = 0,
    agent: Annotated[str, typer.Option(help="scripted, claude or claude:<model>.")] = "claude",
    probability: Annotated[float | None, typer.Option(min=0, max=1)] = None,
    concurrency: Annotated[int, typer.Option(min=1)] = 4,
    trace: Annotated[Path | None, typer.Option(help="JSONL trace path.")] = None,
    judge: Annotated[str, typer.Option(help="auto, keyword, claude or none.")] = "auto",
) -> None:
    """Run a scenario clean and under each fault class, then print a results table."""
    scen = registry.get_scenario(scenario)()
    policies: dict[str, PolicyConfig] = {CLEAN: PolicyConfig()}
    for f in _split(faults):
        policies[f] = policy_for(f, probability)
    for p in _split(profile):
        policies[p] = load_policy({"profile": p})
    if policy:
        policies[policy.stem] = load_policy(policy)
    if len(policies) == 1:
        raise typer.BadParameter("give at least one of --faults, --profile, --policy")
    make_agent(agent, scen)  # validate the spec before starting

    trace = trace or Path("results") / f"{_stamp()}-{scenario}.jsonl"
    with Recorder(trace) as rec:
        runs = asyncio.run(
            run_experiment(
                scen,
                lambda: make_agent(agent, scen),
                policies,
                trials=trials,
                base_seed=seed,
                concurrency=concurrency,
                recorder=rec,
                judge=_judge(judge, agent),
            )
        )
    _print_table(runs, f"{scenario} · {runs[0].agent} · {trials} trials/class · seed {seed}")
    console.print(f"trace: {trace}")


@app.command(name="replay")
def replay_cmd(
    run_id: str,
    trace: Annotated[list[Path] | None, typer.Option(help="Trace file(s) to search.")] = None,
    judge: Annotated[str, typer.Option(help="auto, keyword, claude or none.")] = "auto",
) -> None:
    """Re-run a recorded run with the exact same faults on the same calls."""
    paths = trace or sorted(Path("results").glob("*.jsonl"))
    try:
        recorded = find_run(run_id, paths)
    except KeyError as e:
        raise typer.BadParameter(str(e), param_hint="RUN_ID") from None
    again = asyncio.run(replay(recorded, judge=_judge(judge, recorded.start.agent)))

    before = [(f.call_index, f.tool, f.fault) for f in recorded.faults]
    after = [(f.call_index, f.tool, f.fault) for f in again.faults]
    table = Table(title=f"replay of {run_id} (seed {recorded.start.seed})")
    for col in ("", "faults (call, tool, fault)", "success", "violations"):
        table.add_column(col)
    if recorded.outcome:
        o = recorded.outcome
        table.add_row("recorded", str(before), str(o.task_success), ", ".join(o.safety_violations))
    a = again.outcome
    table.add_row("replayed", str(after), str(a.task_success), ", ".join(a.safety_violations))
    console.print(table)
    if before != after:
        console.print("[red]fault sequence differs[/red]")
        raise typer.Exit(1)
    console.print("[green]fault sequence reproduced[/green]")


@app.command()
def proxy(
    upstream: Annotated[str, typer.Option(help="Upstream command (stdio) or http(s) URL.")],
    profile: Annotated[str | None, typer.Option(help="Built-in profile.")] = None,
    policy: Annotated[Path | None, typer.Option(help="Policy YAML.")] = None,
    seed: Annotated[int | None, typer.Option(help="Overrides the policy seed.")] = None,
    trace: Annotated[Path | None, typer.Option(help="JSONL trace path.")] = None,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run an MCP proxy that injects faults between an agent and an upstream server."""
    from agentchaos.proxies.mcp_proxy import ChaosProxy, serve_http, serve_stdio, upstream_client

    base = load_policy(policy) if policy else PolicyConfig()
    profile_rules = load_policy({"profile": profile}).rules if profile else []
    pol = base.model_copy(update={"rules": profile_rules + base.rules})
    run_id = uuid.uuid4().hex[:12]
    recorder = Recorder(trace) if trace else None

    async def main() -> None:
        async with upstream_client(upstream) as client:
            chaos_proxy = ChaosProxy(
                client, pol, seed=seed, sink=recorder.sink(run_id) if recorder else None
            )
            if recorder:
                recorder.write(
                    RunStart(
                        run_id=run_id,
                        scenario=f"proxy:{upstream}",
                        fault_class=profile or (policy.stem if policy else CLEAN),
                        seed=chaos_proxy.injector.seed,
                        agent="external",
                        policy=pol,
                    )
                )
            err.print(f"agentchaos proxy run {run_id}: {len(pol.rules)} rule(s) -> {upstream}")
            if transport == "http":
                await serve_http(chaos_proxy.server, host, port)
            else:
                await serve_stdio(chaos_proxy.server)

    try:
        asyncio.run(main())
    finally:
        if recorder:
            recorder.close()


@app.command()
def serve(
    scenario: str,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8766,
) -> None:
    """Serve a scenario's fake tool server over MCP (a handy proxy upstream)."""
    from agentchaos.proxies.mcp_proxy import serve_http, serve_stdio
    from agentchaos.scenarios.mcp_server import mcp_server

    server = mcp_server(registry.get_scenario(scenario)().create_server(), scenario)
    asyncio.run(serve_http(server, host, port) if transport == "http" else serve_stdio(server))


@app.command("faults")
def list_faults() -> None:
    """List registered faults (built-in and plugins)."""
    for name, cls in sorted(registry.faults().items()):
        console.print(f"{name:15} {cls.__module__}.{cls.__qualname__}")


@app.command("profiles")
def list_profiles() -> None:
    """List built-in policy profiles."""
    for name in profiles():
        rules = load_policy({"profile": name}).rules
        console.print(f"{name:15} " + ", ".join(f"{r.fault}@{r.probability:g}" for r in rules))


@app.command()
def schema(out: Annotated[Path, typer.Option()] = Path("schemas")) -> None:
    """Regenerate published JSON Schemas."""
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("policy.v1.schema.json", PolicyConfig.model_json_schema()),
        ("trace.v1.schema.json", TypeAdapter(TraceRecord).json_schema()),
    ):
        (out / name).write_text(json.dumps(data, indent=2) + "\n")
        console.print(f"wrote {out / name}")


def _print_table(runs: list[Run], title: str) -> None:
    table = Table(title=title)
    cols = ("class", "success", "95% CI", "vs clean", "unsafe", "surrender", "calls", "faults")
    for col in cols:
        table.add_column(col, justify="left" if col == "class" else "right", no_wrap=True)
    for s in summarize(runs):
        lo, hi = s.success_ci
        table.add_row(
            s.fault_class,
            f"{s.successes}/{s.n} ({s.success_rate:.0%})",
            f"{lo:.0%}-{hi:.0%}",
            "—" if s.degradation is None else f"{s.degradation:.2f}",
            f"{s.safety_violation_rate:.0%}",
            "—" if s.surrender_rate is None else f"{s.surrender_rate:.0%}",
            f"{s.mean_calls:.1f}",
            f"{s.mean_faults:.1f}",
        )
    console.print(table)
    errors = [r for r in runs if r.outcome.agent_error]
    if errors:
        console.print(f"[yellow]{len(errors)} run(s) crashed: {errors[0].outcome.agent_error}")


def _judge(choice: str, agent: str) -> Judge | None:
    if choice == "auto":
        choice = "keyword" if agent == "scripted" else "claude"
    if choice == "none":
        return None
    if choice == "keyword":
        return KeywordJudge()
    if choice == "claude":
        return ClaudeJudge()
    raise typer.BadParameter(f"unknown judge '{choice}'", param_hint="--judge")


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":  # pragma: no cover
    app()
