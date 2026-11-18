"""A deterministic, LLM-free agent that follows a scenario's reference plan.

Used by the test suite and by ``--agent scripted`` so everything runs without
an API key. Its behaviour is deliberately simple and documented, so it is a
fixed yardstick: it retries injected faults up to ``max_retries`` times and
gives up with an explicit surrender message when a step keeps failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentchaos.core.faults import ToolFault
from agentchaos.runners.base import AgentResult, invoke
from agentchaos.scenarios.base import Step, ToolSpec


@dataclass
class ScriptedAgent:
    plan: list[Step]
    max_retries: int = 2
    name: str = "scripted"

    async def run(self, prompt: str, tools: list[ToolSpec]) -> AgentResult:
        by_name = {t.name: t for t in tools}
        results: list[Any] = []
        for step in self.plan:
            args = step.args(results) if callable(step.args) else dict(step.args)
            for attempt in range(self.max_retries + 1):
                try:
                    results.append(await invoke(by_name[step.tool], args))
                    break
                except ToolFault as e:
                    if attempt == self.max_retries:
                        return AgentResult(
                            f"I could not complete the task: '{step.tool}' kept failing ({e})."
                        )
                except Exception as e:  # a real tool error: retrying will not help
                    return AgentResult(f"I could not complete the task: {e}")
        return AgentResult(f"Done. Results: {results[-1] if results else None}")
