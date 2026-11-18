"""Run trials: one fresh server, one injector and one agent per run."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable
from typing import Any

from agentchaos.cache import CostLimitExceeded, ResponseCache
from agentchaos.core import registry
from agentchaos.core.models import FaultRule, Outcome, OutcomeRecord, PolicyConfig, Run, RunStart
from agentchaos.core.policy import Injector, pin_to_events
from agentchaos.core.recorder import RecordedRun, Recorder
from agentchaos.runners import make_agent
from agentchaos.runners.base import Agent, AgentResult
from agentchaos.scenarios.base import Scenario, ToolSpec
from agentchaos.scoring.oracles import Judge

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
    recorder: Recorder | None = None,
    judge: Judge | None = None,
    cache: ResponseCache | None = None,
) -> Run:
    run_id = run_id or uuid.uuid4().hex[:12]
    if recorder:
        recorder.write(
            RunStart(
                run_id=run_id,
                scenario=scenario.name,
                fault_class=fault_class,
                seed=seed,
                agent=agent.name,
                policy=policy,
            )
        )
    server = scenario.create_server()
    injector = Injector(policy, seed=seed, sink=recorder.sink(run_id) if recorder else None)
    tools = [_wrap(t, injector) for t in server.tools()]

    start = time.perf_counter()
    result, agent_error = AgentResult(""), None
    cached_hit = False
    if cache:
        cached = cache.get(agent.name, scenario.name, fault_class, seed, policy)
        if cached is not None:
            result, cached_hit = cached, True
    if not cached_hit:
        try:
            result = await agent.run(scenario.prompt, tools)
        except Exception as e:
            agent_error = f"{type(e).__name__}: {e}"
        if cache and not agent_error:
            cache.put(agent.name, scenario.name, fault_class, seed, policy, result)
        if cache:
            try:
                cache.charge(result.usage.cost_usd)
            except CostLimitExceeded:
                raise
    wall = time.perf_counter() - start

    verdict = scenario.oracle(server.snapshot())
    violations = list(verdict.violations)
    claim = None
    if judge and not verdict.passed and result.final_message:
        claim = await judge.classify(scenario.prompt, result.final_message)
        if claim == "claims_success":
            violations.append("hallucinated_success")

    outcome = Outcome(
        task_success=verdict.passed,
        safety_violations=violations,
        final_message=result.final_message,
        claim=claim,
        agent_error=agent_error,
        details=verdict.details,
    )
    if recorder:
        recorder.write(
            OutcomeRecord(
                run_id=run_id, usage=result.usage, wall_time_s=wall, **outcome.model_dump()
            )
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
        usage=result.usage,
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
    recorder: Recorder | None = None,
    judge: Judge | None = None,
    cache: ResponseCache | None = None,
) -> list[Run]:
    """Run ``trials`` isolated runs per policy, at most ``concurrency`` at a time."""
    sem = asyncio.Semaphore(concurrency)

    async def one(fault_class: str, policy: PolicyConfig, trial: int) -> Run:
        async with sem:
            return await run_trial(
                scenario,
                agent_factory(),
                policy,
                fault_class=fault_class,
                seed=seed_for(base_seed, fault_class, trial),
                recorder=recorder,
                judge=judge,
                cache=cache,
            )

    jobs = [one(fc, p, t) for fc, p in policies.items() for t in range(trials)]
    return list(await asyncio.gather(*jobs))


async def replay(
    recorded: RecordedRun, *, recorder: Recorder | None = None, judge: Judge | None = None
) -> Run:
    """Re-run a recorded run with the same scenario, agent and seed.

    Each policy rule is pinned to the call indices it fired on in the recording,
    so the same faults hit the same calls even if a nondeterministic agent
    makes a different number of calls this time.
    """
    start = recorded.start
    scenario = registry.get_scenario(start.scenario)()
    return await run_trial(
        scenario,
        make_agent(start.agent, scenario),
        pin_to_events(start.policy, list(recorded.faults)),
        fault_class=start.fault_class,
        seed=start.seed,
        recorder=recorder,
        judge=judge,
    )
