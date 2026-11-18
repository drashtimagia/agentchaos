"""Runs must never share state: servers, injectors, call counters or RNG."""

import asyncio

from agentchaos import chaos
from agentchaos.core.faults import ToolTimeoutError
from agentchaos.core.models import FaultRule, PolicyConfig
from agentchaos.core.policy import Injector
from agentchaos.execution import policy_for, run_experiment, run_trial, seed_for
from agentchaos.runners.scripted import ScriptedAgent
from agentchaos.scenarios.tasks.ticketing import TicketingScenario

scen = TicketingScenario()


def test_each_run_gets_a_fresh_server():
    a, b = scen.create_server(), scen.create_server()
    a.create_ticket("x")
    assert b.snapshot()["tickets"] == {}
    assert a.tickets is not b.tickets


async def test_concurrent_runs_do_not_share_state():
    agent = ScriptedAgent(scen.reference_plan())
    runs = await asyncio.gather(
        *[
            run_trial(scen, agent, policy_for("clean"), fault_class="clean", seed=i)
            for i in range(20)
        ]
    )
    for r in runs:
        assert r.outcome.task_success
        assert [c.index for c in r.calls] == [0, 1]  # counters are per run
        assert r.outcome.details["ticket_ids"] == ["T-1"]  # ids restart per server
    assert len({r.run_id for r in runs}) == 20


async def test_experiment_is_reproducible_and_order_independent():
    policies = {"clean": policy_for("clean"), "timeout": policy_for("timeout", 0.5)}

    def factory():
        return ScriptedAgent(scen.reference_plan())

    def key(runs):
        return sorted(
            (r.fault_class, r.seed, r.outcome.task_success, tuple(e.call_index for e in r.faults))
            for r in runs
        )

    a = await run_experiment(scen, factory, policies, trials=15, base_seed=9, concurrency=1)
    b = await run_experiment(scen, factory, policies, trials=15, base_seed=9, concurrency=8)
    assert key(a) == key(b)


def test_seed_for_is_stable_and_distinct():
    assert seed_for(0, "timeout", 3) == seed_for(0, "timeout", 3)
    assert len({seed_for(0, fc, t) for fc in ("a", "b") for t in range(100)}) == 200


async def test_decorator_uses_the_injector_of_its_own_task():
    @chaos.tool
    async def ping(x: int) -> int:
        return x

    always = Injector(PolicyConfig(rules=[FaultRule(fault="timeout")]))
    never = Injector(PolicyConfig())

    async def use(inj):
        with chaos.activate(inj):
            await asyncio.sleep(0)  # let the other task interleave
            try:
                return await ping(1)
            except ToolTimeoutError:
                return "timeout"

    assert await asyncio.gather(use(always), use(never)) == ["timeout", 1]
    assert len(always.calls) == len(never.calls) == 1


async def test_decorator_is_transparent_when_inactive():
    @chaos.tool
    def add(a: int, b: int = 2) -> int:
        return a + b

    assert chaos.current() is None
    assert await add(1) == 3


async def test_decorator_records_bound_args_and_custom_name():
    @chaos.tool(name="search_docs")
    async def search(query: str, limit: int = 5) -> list[str]:
        return [query] * limit

    inj = Injector(PolicyConfig())
    with chaos.activate(inj):
        await search("bugs", limit=2)
    assert inj.calls[0].tool == "search_docs"
    assert inj.calls[0].args == {"query": "bugs", "limit": 2}
