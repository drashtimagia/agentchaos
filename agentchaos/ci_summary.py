"""Write a Markdown summary to ``$GITHUB_STEP_SUMMARY`` (or any file)."""

from __future__ import annotations

import os
from pathlib import Path

from agentchaos.core.models import Run
from agentchaos.scoring.score import summarize


def _pct(v: float) -> str:
    return f"{v:.0%}"


def _deg(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _sr(v: float | None) -> str:
    return "—" if v is None else _pct(v)


def _scenario_table(scenario_name: str, agent: str, runs: list[Run]) -> list[str]:
    lines = [
        f"### {scenario_name} &mdash; {agent}",
        "",
        "| Class | Success | vs clean | Unsafe | Surrender | Calls |",
        "| ----- | ------- | -------- | ------ | --------- | ----- |",
    ]
    for s in summarize(runs):
        _lo, _hi = s.success_ci
        lines.append(
            f"| {s.fault_class} "
            f"| {s.successes}/{s.n} ({_pct(s.success_rate)}) "
            f"| {_deg(s.degradation)} "
            f"| {_pct(s.safety_violation_rate)} "
            f"| {_sr(s.surrender_rate)} "
            f"| {s.mean_calls:.1f} |"
        )
    return lines


def write_summary(
    bench_results: dict[str, dict[str, list[Run]]],
    *,
    path: Path | None = None,
) -> None:
    """Write a Markdown summary.

    If ``path`` is None the value of ``$GITHUB_STEP_SUMMARY`` is used.
    Silently does nothing when neither is set.
    """
    target = path
    if target is None:
        env = os.environ.get("GITHUB_STEP_SUMMARY")
        if not env:
            return
        target = Path(env)

    lines = ["## AgentChaos Benchmark", ""]
    for scenario_name, by_agent in bench_results.items():
        for agent_name, runs in by_agent.items():
            lines.extend(_scenario_table(scenario_name, agent_name, runs))
            lines.append("")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
