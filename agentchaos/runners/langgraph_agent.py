"""Runner for LangGraph's prebuilt ReAct agent (``pip install 'agentchaos[langgraph]'``).

Each tool spec becomes a LangChain ``StructuredTool``; the agent runs with
``create_react_agent`` from ``langgraph.prebuilt``.

Env vars: ``AGENTCHAOS_LANGGRAPH_MODEL`` (default ``gpt-4o``) and the usual
``OPENAI_API_KEY`` (or swap in a different chat model via the env var).
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


class LangGraphRunner:
    def __init__(self, model: str | None = None, max_steps: int = 40):
        self.model = model or os.environ.get("AGENTCHAOS_LANGGRAPH_MODEL", DEFAULT_MODEL)
        self.max_steps = max_steps
        self.name = f"langgraph:{self.model}"

    async def run(self, prompt: str, tools: list[ToolSpec]) -> AgentResult:
        try:
            from langchain_openai import ChatOpenAI
            from langgraph.prebuilt import create_react_agent
        except ImportError as e:
            raise RuntimeError("Install the extra: pip install 'agentchaos[langgraph]'") from e

        llm = ChatOpenAI(model=self.model)
        lc_tools = [_adapt(t) for t in tools]
        agent = create_react_agent(llm, lc_tools)

        config = {"recursion_limit": self.max_steps}
        result = await agent.ainvoke({"messages": [("user", prompt)]}, config=config)

        messages = result.get("messages", [])
        final = ""
        for msg in reversed(messages):
            text = getattr(msg, "content", "")
            if isinstance(text, str) and text.strip():
                final = text.strip()
                break

        return AgentResult(final or "Done.", Usage())


def _adapt(spec: ToolSpec) -> Any:
    from langchain_core.tools import StructuredTool
    from pydantic import create_model

    fields: dict[str, Any] = {}
    props = (spec.parameters or {}).get("properties", {})
    required = set((spec.parameters or {}).get("required", []))
    for name, schema in props.items():
        annotation = _py_type(schema)
        default = ... if name in required else None
        fields[name] = (annotation, default)

    ArgsModel = create_model(f"{spec.name}_args", **fields) if fields else None

    async def coroutine(**kwargs: Any) -> str:
        try:
            result = await spec.call(kwargs)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as e:
            return f"Error: {e}"

    if ArgsModel:
        return StructuredTool.from_function(
            coroutine=coroutine,
            name=spec.name,
            description=spec.description,
            args_schema=ArgsModel,
        )
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=spec.name,
        description=spec.description,
    )


def _py_type(schema: dict[str, Any]) -> type:
    t = schema.get("type")
    if t == "string":
        return str
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    return Any
