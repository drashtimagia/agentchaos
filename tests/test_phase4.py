"""Phase 4: pytest plugin, OTel export, example plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentchaos.core.models import PolicyConfig

# ---------------------------------------------------------------------------
# pytest plugin fixtures and marker
# ---------------------------------------------------------------------------


def test_chaos_policy_fixture_no_marker(chaos_policy):
    assert chaos_policy == PolicyConfig()


@pytest.mark.chaos(profile="rate-limited")
def test_chaos_policy_fixture_with_profile_marker(chaos_policy):
    assert len(chaos_policy.rules) > 0
    assert any(r.fault == "rate_limit" for r in chaos_policy.rules)


@pytest.mark.chaos(faults="timeout", probability=0.5, seed=7)
def test_chaos_policy_fixture_with_faults_marker(chaos_policy):
    assert len(chaos_policy.rules) == 1
    assert chaos_policy.rules[0].fault == "timeout"
    assert chaos_policy.rules[0].probability == 0.5
    assert chaos_policy.seed == 7


@pytest.mark.chaos(faults="timeout,rate_limit")
def test_chaos_policy_fixture_multiple_faults(chaos_policy):
    assert len(chaos_policy.rules) == 2
    names = {r.fault for r in chaos_policy.rules}
    assert names == {"timeout", "rate_limit"}


def test_chaos_injector_fixture_activates(chaos_injector):
    from agentchaos.core import decorator

    assert decorator._active.get() is not None


def test_chaos_injector_fixture_deactivates_after(request):
    from agentchaos.core import decorator

    assert decorator._active.get() is None


# ---------------------------------------------------------------------------
# OTel export (mocked SDK)
# ---------------------------------------------------------------------------


def _make_trace_jsonl(tmp_path: Path) -> Path:

    from agentchaos.core.models import (
        FaultRecord,
        OutcomeRecord,
        PolicyConfig,
        RunStart,
        ToolCallRecord,
        Usage,
    )

    path = tmp_path / "trace.jsonl"
    records = [
        RunStart(
            run_id="abc123",
            scenario="ticketing",
            fault_class="timeout",
            seed=0,
            agent="scripted",
            policy=PolicyConfig(),
        ),
        ToolCallRecord(
            run_id="abc123",
            tool="create_ticket",
            args={},
            result=None,
            index=0,
            ok=True,
            duration_ms=10.0,
        ),
        FaultRecord(
            run_id="abc123",
            tool="create_ticket",
            fault="timeout",
            call_index=0,
            rule=0,
            detail={},
        ),
        OutcomeRecord(
            run_id="abc123",
            task_success=False,
            safety_violations=[],
            final_message="failed",
            claim=None,
            agent_error=None,
            details={},
            usage=Usage(),
            wall_time_s=0.1,
        ),
    ]
    with path.open("w") as fh:
        for rec in records:
            fh.write(rec.model_dump_json() + "\n")
    return path


def test_export_otel_raises_without_sdk(tmp_path):
    """export_trace raises RuntimeError when opentelemetry-sdk is not installed."""
    import sys

    # Simulate missing SDK by blocking the import
    blocked = {
        "opentelemetry": None,
        "opentelemetry.sdk": None,
        "opentelemetry.sdk.trace": None,
        "opentelemetry.exporter": None,
        "opentelemetry.exporter.otlp": None,
        "opentelemetry.exporter.otlp.proto": None,
        "opentelemetry.exporter.otlp.proto.grpc": None,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
        "opentelemetry.sdk.resources": None,
        "opentelemetry.sdk.trace.export": None,
    }
    # Also evict agentchaos.otel so its import-time guard is re-evaluated
    saved_otel = sys.modules.pop("agentchaos.otel", None)
    try:
        with patch.dict("sys.modules", blocked):
            import importlib

            import agentchaos.otel as otel_mod

            importlib.reload(otel_mod)
            with pytest.raises((RuntimeError, ImportError)):
                otel_mod.export_trace(tmp_path / "nonexistent.jsonl")
    finally:
        if saved_otel is not None:
            sys.modules["agentchaos.otel"] = saved_otel


# ---------------------------------------------------------------------------
# Example plugin: SlackRateLimit
# ---------------------------------------------------------------------------


def test_slack_fault_raises_tool_fault():
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "examples" / "slack_fault"))
    try:
        import asyncio

        from slack_fault import SlackRateLimit

        from agentchaos.core.faults import ToolCallContext, ToolFault

        fault = SlackRateLimit(retry_after=15)

        async def always_fire():
            # Force fire by patching rng to return 0
            ctx2 = ToolCallContext(
                tool="post_message",
                args={},
                call_index=0,
                rng=MagicMock(random=lambda: 0.0),
                rule=0,
                history=[],
                fired=[],
            )

            async def call_next(c):
                return "ok"

            with pytest.raises(ToolFault, match="429"):
                await fault.apply(ctx2, call_next)

        asyncio.run(always_fire())
    finally:
        sys.path.pop(0)
