"""Agent runners. ``make_agent`` turns a spec string into a fresh agent.

Specs: ``scripted`` (no LLM), ``claude`` or ``claude:<model>`` (Claude Agent SDK).
A run records its agent's ``name``, which is itself a valid spec, so replay can
rebuild the same agent.
"""

from __future__ import annotations

from agentchaos.runners.base import Agent
from agentchaos.scenarios.base import Scenario


def make_agent(spec: str, scenario: Scenario) -> Agent:
    kind, _, arg = spec.partition(":")
    if kind == "scripted":
        from agentchaos.runners.scripted import ScriptedAgent

        return ScriptedAgent(scenario.reference_plan())
    if kind == "claude":
        from agentchaos.runners.claude_agent import ClaudeAgentRunner

        return ClaudeAgentRunner(model=arg or None)
    raise ValueError(f"Unknown agent '{spec}'. Use 'scripted', 'claude' or 'claude:<model>'.")
