"""Phase 3: cache, bench command, HTML report, CI summary, new runners."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentchaos.cache import CostLimitExceeded, ResponseCache
from agentchaos.cli import app
from agentchaos.core.models import PolicyConfig, Usage
from agentchaos.execution import CLEAN
from agentchaos.runners.base import AgentResult
from agentchaos.scenarios.tasks.ticketing import TicketingScenario

# ---------------------------------------------------------------------------
# ResponseCache
# ---------------------------------------------------------------------------


def test_cache_miss(tmp_path):
    cache = ResponseCache(directory=tmp_path)
    scen = TicketingScenario()
    result = cache.get("scripted", scen.name, CLEAN, 0, PolicyConfig())
    assert result is None


def test_cache_roundtrip(tmp_path):
    cache = ResponseCache(directory=tmp_path)
    scen = TicketingScenario()
    policy = PolicyConfig()
    stored = AgentResult("Done.", Usage(input_tokens=10, output_tokens=5, cost_usd=0.001))
    cache.put("scripted", scen.name, CLEAN, 0, policy, stored)
    retrieved = cache.get("scripted", scen.name, CLEAN, 0, policy)
    assert retrieved is not None
    assert retrieved.final_message == "Done."
    assert retrieved.usage.input_tokens == 10


def test_cache_different_seeds_are_different_slots(tmp_path):
    cache = ResponseCache(directory=tmp_path)
    scen = TicketingScenario()
    policy = PolicyConfig()
    cache.put("scripted", scen.name, CLEAN, 1, policy, AgentResult("seed1"))
    assert cache.get("scripted", scen.name, CLEAN, 2, policy) is None
    assert cache.get("scripted", scen.name, CLEAN, 1, policy) is not None


def test_max_cost_guard(tmp_path):
    cache = ResponseCache(directory=tmp_path, max_cost_usd=0.005)
    cache.charge(0.003)  # fine
    with pytest.raises(CostLimitExceeded):
        cache.charge(0.003)  # pushes over 0.005


def test_cost_accumulates(tmp_path):
    cache = ResponseCache(directory=tmp_path)
    cache.charge(0.01)
    cache.charge(0.02)
    assert abs(cache.spent - 0.03) < 1e-9


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def _make_runs(scenario: str = "ticketing", agent: str = "scripted", n: int = 4):
    from agentchaos.core.models import Outcome, Run, Usage

    def run(fc: str, success: bool) -> Run:
        return Run(
            run_id="x",
            scenario=scenario,
            fault_class=fc,
            seed=0,
            agent=agent,
            calls=[],
            faults=[],
            outcome=Outcome(task_success=success, safety_violations=[], final_message=""),
            usage=Usage(),
            wall_time_s=0.1,
        )

    return [run(CLEAN, True), run(CLEAN, True), run("timeout", True), run("timeout", False)]


def test_html_report_contains_scenario_and_agent(tmp_path):
    from agentchaos.report import write_report

    runs = _make_runs()
    out = tmp_path / "report.html"
    write_report({"ticketing": {"scripted": runs}}, out, title_meta="test run")
    content = out.read_text()
    assert "ticketing" in content
    assert "scripted" in content
    assert "timeout" in content
    assert "<!doctype html>" in content.lower()


def test_html_report_is_self_contained(tmp_path):
    from agentchaos.report import write_report

    runs = _make_runs()
    out = tmp_path / "report.html"
    write_report({"ticketing": {"scripted": runs}}, out)
    content = out.read_text()
    # No external stylesheet or script references
    assert "<link" not in content
    assert "<script src" not in content


# ---------------------------------------------------------------------------
# CI summary
# ---------------------------------------------------------------------------


def test_ci_summary_writes_markdown(tmp_path):
    from agentchaos.ci_summary import write_summary

    runs = _make_runs()
    out = tmp_path / "summary.md"
    write_summary({"ticketing": {"scripted": runs}}, path=out)
    content = out.read_text()
    assert "ticketing" in content
    assert "scripted" in content
    assert "|" in content  # markdown table


def test_ci_summary_uses_env_var(tmp_path, monkeypatch):
    from agentchaos.ci_summary import write_summary

    out = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(out))
    runs = _make_runs()
    write_summary({"ticketing": {"scripted": runs}})
    assert out.exists()
    assert "timeout" in out.read_text()


def test_ci_summary_silent_when_no_target(monkeypatch):
    from agentchaos.ci_summary import write_summary

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    # should not raise
    write_summary({"ticketing": {"scripted": _make_runs()}})


# ---------------------------------------------------------------------------
# bench CLI command
# ---------------------------------------------------------------------------


def test_bench_smoke_mode(tmp_path):
    runner = CliRunner(env={"COLUMNS": "200"})
    trace = tmp_path / "bench.jsonl"
    res = runner.invoke(
        app,
        [
            "bench",
            "--scenarios",
            "ticketing",
            "--agents",
            "scripted",
            "--profile",
            "rate-limited",
            "--smoke",
            "--trace",
            str(trace),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "ticketing" in res.output
    assert trace.exists()


def test_bench_generates_html_report(tmp_path):
    runner = CliRunner(env={"COLUMNS": "200"})
    report = tmp_path / "report.html"
    res = runner.invoke(
        app,
        [
            "bench",
            "--scenarios",
            "ticketing",
            "--agents",
            "scripted",
            "--profile",
            "rate-limited",
            "--smoke",
            "--report",
            str(report),
            "--trace",
            str(tmp_path / "t.jsonl"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert report.exists()
    assert "<!doctype html>" in report.read_text().lower()


def test_bench_ci_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    runner = CliRunner(env={"COLUMNS": "200"})
    res = runner.invoke(
        app,
        [
            "bench",
            "--scenarios",
            "ticketing",
            "--agents",
            "scripted",
            "--profile",
            "rate-limited",
            "--smoke",
            "--ci",
            "--trace",
            str(tmp_path / "t.jsonl"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert summary.exists()


# ---------------------------------------------------------------------------
# New runner module structure (import-only, no API key needed)
# ---------------------------------------------------------------------------


def test_make_agent_openai_spec_creates_runner():
    from agentchaos.runners import make_agent
    from agentchaos.runners.openai_agents import OpenAIAgentsRunner
    from agentchaos.scenarios.tasks.ticketing import TicketingScenario

    agent = make_agent("openai:gpt-4o-mini", TicketingScenario())
    assert isinstance(agent, OpenAIAgentsRunner)
    assert agent.name == "openai:gpt-4o-mini"


def test_make_agent_langgraph_spec_creates_runner():
    from agentchaos.runners import make_agent
    from agentchaos.runners.langgraph_agent import LangGraphRunner
    from agentchaos.scenarios.tasks.ticketing import TicketingScenario

    agent = make_agent("langgraph:gpt-4o-mini", TicketingScenario())
    assert isinstance(agent, LangGraphRunner)
    assert agent.name == "langgraph:gpt-4o-mini"


def test_make_agent_unknown_spec_raises():
    from agentchaos.runners import make_agent
    from agentchaos.scenarios.tasks.ticketing import TicketingScenario

    with pytest.raises(ValueError, match="Unknown agent"):
        make_agent("unknown_framework", TicketingScenario())
