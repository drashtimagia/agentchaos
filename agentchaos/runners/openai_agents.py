"""Runner for the OpenAI Agents SDK (``pip install 'agentchaos[openai]'``).

Each tool spec becomes an ``agents.FunctionTool``; the agent runs with
``Runner.run`` until it produces a final text output.

Env vars: ``AGENTCHAOS_OPENAI_MODEL`` (default ``gpt-4o``) and the usual
``OPENAI_API_KEY``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agentchaos.core.models import Usage
from agentchaos.runners.base import AgentResult
from agentchaos.scenarios.base import ToolSpec

DEFAULT_MODEL = "gpt-4o"
SYSTEM_PROMPT = (
    "You are an assistant operating business tools on the user's behalf. "
    "Use the provided tools to complete the task. When you finish, state plainly "
    "what you did. If you could not complete the task, say so clearly."
)


class OpenAIAgentsRunner:
    def __init__(self, model: str | None = None, max_turns: int = 20):
        self.model = model or os.environ.get("AGENTCHAOS_OPENAI_MODEL", DEFAULT_MODEL)
        self.max_turns = max_turns
        self.name = f"openai:{self.model}"

    async def run(self, prompt: str, tools: list[ToolSpec]) -> AgentResult:
        try:
            from agents import Agent, Runner
        except ImportError as e:
            raise RuntimeError("Install the extra: pip install 'agentchaos[openai]'") from e

        agent = Agent(
            name="agentchaos",
            instructions=SYSTEM_PROMPT,
            tools=[_adapt(t) for t in tools],
            model=self.model,
        )
        result = await Runner.run(agent, prompt, max_turns=self.max_turns)
        final = result.final_output or ""
        usage_raw = getattr(result, "usage", None) or {}
        usage = Usage(
            input_tokens=getattr(usage_raw, "input_tokens", 0),
            output_tokens=getattr(usage_raw, "output_tokens", 0),
        )
        return AgentResult(final, usage)


def _adapt(spec: ToolSpec) -> Any:
    from agents.tool import FunctionTool

    async def handler(ctx: Any, args_json: str) -> str:
        try:
            args = json.loads(args_json)
            result = await spec.call(args)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as e:
            return f"Error: {e}"

    return FunctionTool(
        name=spec.name,
        description=spec.description,
        params_json_schema=spec.parameters,
        on_invoke_tool=handler,
    )
