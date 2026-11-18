import json

import pytest
from typer.testing import CliRunner

from agentchaos.cli import app
from agentchaos.scoring.score import wilson

runner = CliRunner(env={"COLUMNS": "200"})


def invoke(*args):
    return runner.invoke(app, [str(a) for a in args])


def test_wilson_bounds():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.75
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi


def test_run_command_with_scripted_agent(tmp_path):
    trace = tmp_path / "t.jsonl"
    res = invoke(
        "run",
        "--faults",
        "timeout,rate_limit,fail_after",
        "--trials",
        10,
        "--agent",
        "scripted",
        "--trace",
        trace,
    )
    assert res.exit_code == 0, res.output
    for fc in ("clean", "timeout", "rate_limit", "fail_after"):
        assert fc in res.output
    assert "10/10 (100%)" in res.output  # clean baseline
    assert len([line for line in trace.read_text().splitlines()]) > 40


def test_run_command_with_policy_file_and_profile(tmp_path):
    p = tmp_path / "mine.yaml"
    p.write_text("schema_version: 1\nrules:\n  - fault: rate_limit\n    probability: 0.2\n")
    res = invoke(
        "run",
        "--scenario",
        "inventory",
        "--policy",
        p,
        "--profile",
        "stale-cache",
        "--trials",
        3,
        "--agent",
        "scripted",
        "--trace",
        tmp_path / "t.jsonl",
    )
    assert res.exit_code == 0, res.output
    assert "mine" in res.output and "stale-cache" in res.output


@pytest.mark.parametrize(
    "args",
    [["--faults", "nope"], ["--profile", "nope"], [], ["--faults", "timeout", "--agent", "x"]],
)
def test_bad_run_arguments_error(args, tmp_path):
    res = invoke("run", "--agent", "scripted", "--trace", tmp_path / "t.jsonl", *args)
    assert res.exit_code != 0


def test_replay_command_reproduces(tmp_path):
    trace = tmp_path / "t.jsonl"
    invoke(
        "run",
        "--faults",
        "malformed_json",
        "--probability",
        1,
        "--trials",
        2,
        "--agent",
        "scripted",
        "--trace",
        trace,
    )
    runs = [json.loads(line) for line in trace.read_text().splitlines()]
    run_id = next(r["run_id"] for r in runs if r["type"] == "fault")
    res = invoke("replay", run_id, "--trace", trace)
    assert res.exit_code == 0, res.output
    assert "fault sequence reproduced" in res.output


def test_replay_unknown_run(tmp_path):
    (tmp_path / "t.jsonl").write_text("")
    assert invoke("replay", "nope", "--trace", tmp_path / "t.jsonl").exit_code != 0


def test_listing_commands():
    assert all(n in invoke("faults").output for n in ("timeout", "schema_drift", "stale_data"))
    assert "flaky-network" in invoke("profiles").output
