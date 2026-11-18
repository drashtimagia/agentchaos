"""Tests for agentchaos.scoring."""

from __future__ import annotations

from agentchaos.core.models import Outcome, Run, Usage
from agentchaos.scoring.score import (
    AgentScore,
    score_agent,
    score_bench,
    score_runs,
)


def _run(
    *,
    task_success: bool = True,
    safety_violations: list[str] | None = None,
    agent_error: str | None = None,
    claim: str | None = None,
    agent: str = "scripted",
    fault_class: str = "timeout",
    seed: int = 0,
) -> Run:
    return Run(
        run_id="x",
        scenario="ticketing",
        fault_class=fault_class,
        seed=seed,
        agent=agent,
        outcome=Outcome(
            task_success=task_success,
            safety_violations=safety_violations or [],
            agent_error=agent_error,
            claim=claim,  # type: ignore[arg-type]
        ),
        usage=Usage(),
        wall_time_s=0.1,
    )


def test_perfect_runs():
    runs = [_run(task_success=True) for _ in range(10)]
    fs = score_runs(runs)
    assert fs.score == 100.0
    assert fs.task_success.rate == 1.0
    assert fs.safety.rate == 1.0
    assert fs.execution.rate == 1.0
    # graceful failure: no failures, so defaults to 1.0
    assert fs.graceful_failure.rate == 1.0


def test_all_failing_no_acknowledgement():
    runs = [_run(task_success=False) for _ in range(10)]
    fs = score_runs(runs)
    assert fs.task_success.rate == 0.0
    assert fs.graceful_failure.rate == 0.0
    assert fs.score < 50.0


def test_graceful_failure_counts_acknowledged():
    runs = [
        _run(task_success=False, claim="reports_failure"),
        _run(task_success=False, claim="reports_failure"),
        _run(task_success=False),  # not acknowledged
    ]
    fs = score_runs(runs)
    assert abs(fs.graceful_failure.rate - 2 / 3) < 1e-9


def test_safety_violation_lowers_score():
    clean = [_run(task_success=True) for _ in range(10)]
    unsafe = [_run(task_success=True, safety_violations=["pii_leak"]) for _ in range(10)]
    fs_clean = score_runs(clean)
    fs_unsafe = score_runs(unsafe)
    assert fs_clean.score > fs_unsafe.score
    assert fs_unsafe.safety.rate == 0.0


def test_agent_error_lowers_execution():
    runs = [_run(agent_error="Traceback...") for _ in range(5)]
    fs = score_runs(runs)
    assert fs.execution.rate == 0.0


def test_score_agent_averages_fault_classes():
    fs1 = score_runs([_run(fault_class="timeout")] * 5)
    fs2 = score_runs([_run(fault_class="rate_limit", task_success=False)] * 5)
    ag = score_agent([fs1, fs2])
    assert isinstance(ag, AgentScore)
    assert abs(ag.score - (fs1.score + fs2.score) / 2) < 1e-9


def test_score_bench_groups_by_agent():
    bench: dict[str, dict[str, list[Run]]] = {
        "ticketing": {
            "scripted": [_run(agent="scripted", fault_class="timeout")] * 5,
            "claude": [_run(agent="claude", fault_class="timeout")] * 5,
        }
    }
    scores = score_bench(bench)
    assert "scripted" in scores
    assert "claude" in scores


def test_ci_bounds_are_valid():
    runs = [_run(task_success=(i % 2 == 0)) for i in range(20)]
    fs = score_runs(runs)
    assert fs.score_ci_lo <= fs.score <= fs.score_ci_hi
    assert fs.score_ci_lo >= 0.0
    assert fs.score_ci_hi <= 100.0
