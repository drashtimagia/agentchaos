"""The thin contract every agent runner implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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
