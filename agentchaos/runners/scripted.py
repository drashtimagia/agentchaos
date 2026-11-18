"""A deterministic, LLM-free agent that follows a scenario's reference plan.

Used by the test suite and by ``--agent scripted`` so everything runs without
an API key. Its behaviour is deliberately simple and documented, so it is a
fixed yardstick:

- injected faults and unparseable responses are retried up to ``max_retries`` times;
- real tool errors and responses it cannot use are not retried;
- when it gives up, it says so plainly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agentchaos.core.faults import ToolFault
from agentchaos.core.payload import RawText
from agentchaos.runners.base import AgentResult
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
            try:
                if step.when and not step.when(results):
                    continue
                args = step.args(results) if callable(step.args) else dict(step.args)
            except (KeyError, TypeError, IndexError) as e:
                return _give_up(f"an earlier response was missing data I needed ({e!r})")
            for attempt in range(self.max_retries + 1):
                try:
                    result = await by_name[step.tool].call(args)
                    results.append(json.loads(result) if isinstance(result, RawText) else result)
                    break
                except (ToolFault, json.JSONDecodeError) as e:
                    if attempt == self.max_retries:
                        return _give_up(f"'{step.tool}' kept failing ({e})")
                except Exception as e:
                    return _give_up(str(e))
        return AgentResult("Done.")


def _give_up(reason: str) -> AgentResult:
    return AgentResult(f"I could not complete the task: {reason}.")
