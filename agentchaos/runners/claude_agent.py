"""Runner for the Claude Agent SDK (``pip install 'agentchaos[claude]'``).

Scenario tools are exposed to the agent through an in-process SDK MCP server.
All built-in Claude Code tools are disabled and no user/project settings are
loaded, so the agent sees only the scenario's tools.

Env vars: ``AGENTCHAOS_MODEL`` (default ``claude-opus-5-5``) and the usual
``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agentchaos.core.models import Usage
from agentchaos.runners.base import AgentResult, invoke
from agentchaos.scenarios.base import ToolSpec

DEFAULT_MODEL = "claude-opus-5-5"
SYSTEM_PROMPT = (
    "You are an assistant operating business tools on the user's behalf. "
    "Use the provided tools to complete the task. When you finish, state plainly "
    "what you did. If you could not complete the task, say so clearly."
)
SERVER = "tools"


class ClaudeAgentRunner:
    def __init__(self, model: str | None = None, max_turns: int = 20):
        self.model = model or os.environ.get("AGENTCHAOS_MODEL", DEFAULT_MODEL)
        self.max_turns = max_turns
        self.name = f"claude-agent-sdk:{self.model}"

    async def run(self, prompt: str, tools: list[ToolSpec]) -> AgentResult:
        try:
            import claude_agent_sdk as sdk
        except ImportError as e:  # pragma: no cover - depends on optional extra
            raise RuntimeError("Install the extra: pip install 'agentchaos[claude]'") from e

        server = sdk.create_sdk_mcp_server(SERVER, tools=[_adapt(sdk, t) for t in tools])
        options = sdk.ClaudeAgentOptions(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools=[],  # no built-in tools
            mcp_servers={SERVER: server},
            allowed_tools=[f"mcp__{SERVER}__{t.name}" for t in tools],
            setting_sources=[],  # isolate from the user's Claude Code settings
            max_turns=self.max_turns,
        )
        texts: list[str] = []
        usage = Usage()
        final = ""
        async for msg in sdk.query(prompt=prompt, options=options):
            if isinstance(msg, sdk.AssistantMessage):
                texts += [b.text for b in msg.content if isinstance(b, sdk.TextBlock)]
            elif isinstance(msg, sdk.ResultMessage):
                u = msg.usage or {}
                usage = Usage(
                    input_tokens=u.get("input_tokens", 0),
                    output_tokens=u.get("output_tokens", 0),
                    cost_usd=msg.total_cost_usd or 0.0,
                )
                final = msg.result or ""
        return AgentResult(final or (texts[-1] if texts else ""), usage)


def _adapt(sdk: Any, spec: ToolSpec) -> Any:
    @sdk.tool(spec.name, spec.description, spec.parameters)
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await invoke(spec, args)
        except Exception as e:  # faults and tool errors both reach the model as errors
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    return handler
