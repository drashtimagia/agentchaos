"""Run trials: one fresh server, one injector and one agent per run."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable
from typing import Any

from agentchaos.core import registry
from agentchaos.core.models import FaultRule, Outcome, PolicyConfig, Run, Usage
from agentchaos.core.policy import Injector
from agentchaos.runners.base import Agent
from agentchaos.scenarios.base import Scenario, ToolSpec

CLEAN = "clean"


def seed_for(base_seed: int, fault_class: str, trial: int) -> int:
    """Stable per-trial seed, independent of execution order and concurrency."""
    digest = hashlib.sha256(f"{base_seed}:{fault_class}:{trial}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def policy_for(fault: str, probability: float | None = None, **params: Any) -> PolicyConfig:
    """A one-rule policy applying ``fault`` to every tool. ``clean`` means no rules."""
    if fault == CLEAN:
        return PolicyConfig()
    cls = registry.get_fault(fault)
    p = cls.default_probability if probability is None else probability
    return PolicyConfig(rules=[FaultRule(fault=fault, probability=p, params=params)])


def _wrap(spec: ToolSpec, injector: Injector) -> ToolSpec:
    async def fn(**args: Any) -> Any:
        return await injector.call(spec.name, args, spec.fn)

    return ToolSpec(spec.name, spec.description, spec.parameters, fn)


async def run_trial(
    scenario: Scenario,
    agent: Agent,
    policy: PolicyConfig,
    *,
    fault_class: str,
    seed: int,
    run_id: str | None = None,
) -> Run:
    run_id = run_id or uuid.uuid4().hex[:12]
    server = scenario.create_server()
    injector = Injector(policy, run_id=run_id, seed=seed)
    tools = [_wrap(t, injector) for t in server.tools()]

    start = time.perf_counter()
    final, usage, agent_error = "", Usage(), None
    try:
        result = await agent.run(scenario.prompt, tools)
        final, usage = result.final_message, result.usage
    except Exception as e:
        agent_error = f"{type(e).__name__}: {e}"
    wall = time.perf_counter() - start

    verdict = scenario.oracle(server.snapshot())
    outcome = Outcome(
        task_success=verdict.passed,
        safety_violations=verdict.violations,
        final_message=final,
        agent_error=agent_error,
        details=verdict.details,
    )
    return Run(
        run_id=run_id,
        scenario=scenario.name,
        fault_class=fault_class,
        seed=seed,
        agent=agent.name,
        calls=injector.calls,
        faults=injector.events,
        outcome=outcome,
        usage=usage,
        wall_time_s=wall,
    )


async def run_experiment(
    scenario: Scenario,
    agent_factory: Callable[[], Agent],
    policies: dict[str, PolicyConfig],
    *,
    trials: int,
    base_seed: int = 0,
    concurrency: int = 4,
) -> list[Run]:
    """Run ``trials`` isolated runs per policy, at most ``concurrency`` at a time."""
    sem = asyncio.Semaphore(concurrency)

    async def one(fault_class: str, policy: PolicyConfig, trial: int) -> Run:
        async with sem:
            seed = seed_for(base_seed, fault_class, trial)
            return await run_trial(
                scenario, agent_factory(), policy, fault_class=fault_class, seed=seed
            )

    jobs = [one(fc, p, t) for fc, p in policies.items() for t in range(trials)]
    return list(await asyncio.gather(*jobs))
