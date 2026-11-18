from typer.testing import CliRunner

from agentchaos.cli import app
from agentchaos.scoring.score import wilson

runner = CliRunner()


def test_wilson_bounds():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.75
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi


def test_run_command_with_scripted_agent():
    res = runner.invoke(
        app,
        [
            "run",
            "--scenario",
            "ticketing",
            "--faults",
            "timeout,rate_limit,fail_after",
            "--trials",
            "10",
            "--agent",
            "scripted",
        ],
    )
    assert res.exit_code == 0, res.output
    for fc in ("clean", "timeout", "rate_limit", "fail_after"):
        assert fc in res.output
    assert "10/10 (100%)" in res.output  # clean baseline


def test_run_command_with_policy_file(tmp_path):
    p = tmp_path / "mine.yaml"
    p.write_text("schema_version: 1\nrules:\n  - fault: rate_limit\n    probability: 0.2\n")
    res = runner.invoke(app, ["run", "--policy", str(p), "--trials", "3", "--agent", "scripted"])
    assert res.exit_code == 0, res.output
    assert "mine" in res.output


def test_unknown_fault_errors():
    res = runner.invoke(app, ["run", "--faults", "nope", "--agent", "scripted"])
    assert res.exit_code != 0


def test_faults_command_lists_builtins():
    res = runner.invoke(app, ["faults"])
    assert all(n in res.output for n in ("timeout", "rate_limit", "fail_after"))
