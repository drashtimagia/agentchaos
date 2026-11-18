"""The thin contract every agent runner implements."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentchaos.core.models import Usage
from agentchaos.scenarios.base import ToolSpec


@dataclass
class AgentResult:
    final_message: str
    usage: Usage = field(default_factory=Usage)


class Agent(Protocol):
    """Runs one task to completion with the given (already chaos-wrapped) tools."""

    name: str

    async def run(self, prompt: str, tools: list[ToolSpec]) -> AgentResult: ...


async def invoke(tool: ToolSpec, args: dict[str, Any]) -> Any:
    result = tool.fn(**args)
    return await result if inspect.isawaitable(result) else result
