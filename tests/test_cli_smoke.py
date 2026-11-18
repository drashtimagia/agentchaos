"""CLI smoke tests: --version, --help, faults, profiles, scenarios."""

from __future__ import annotations

from typer.testing import CliRunner

from agentchaos import __version__
from agentchaos.cli import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_flag():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "agentchaos" in result.output.lower()


def test_faults_command():
    result = runner.invoke(app, ["faults"])
    assert result.exit_code == 0
    # built-in faults must all appear
    for name in ("timeout", "rate_limit", "latency", "malformed_json", "stale_data"):
        assert name in result.output


def test_profiles_command():
    result = runner.invoke(app, ["profiles"])
    assert result.exit_code == 0
    assert "flaky-network" in result.output


def test_schema_command(tmp_path):
    result = runner.invoke(app, ["schema", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "policy.v1.schema.json").exists()
