"""The Claude runner's tool adapter, tested without calling the model."""

import pytest

from agentchaos.core.faults import RateLimitError
from agentchaos.runners.claude_agent import _adapt
from agentchaos.scenarios.base import ToolSpec

sdk = pytest.importorskip("claude_agent_sdk")


async def test_adapter_returns_json_result():
    spec = ToolSpec("echo", "Echo.", {"type": "object"}, lambda **kw: {"got": kw})
    out = await _adapt(sdk, spec).handler({"x": 1})
    assert out == {"content": [{"type": "text", "text": '{"got": {"x": 1}}'}]}


async def test_adapter_surfaces_faults_as_tool_errors():
    def limited(**kw):
        raise RateLimitError(3)

    out = await _adapt(sdk, ToolSpec("t", "T.", {"type": "object"}, limited)).handler({})
    assert out["is_error"] is True
    assert "429" in out["content"][0]["text"]
