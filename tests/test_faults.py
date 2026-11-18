import contextlib
import json

import pytest

from agentchaos.core.faults import (
    RateLimitError,
    ToolFault,
    ToolTimeoutError,
    UpstreamError,
)
from agentchaos.core.models import FaultRule, PolicyConfig
from agentchaos.core.payload import RawText
from agentchaos.core.policy import Injector


class Counter:
    def __init__(self):
        self.calls = 0

    async def __call__(self, **kw):
        self.calls += 1
        return {"ok": True, **kw}


def injector(fault: str, probability: float = 1.0, seed: int = 0, **params) -> Injector:
    rule = FaultRule(fault=fault, probability=probability, params=params)
    return Injector(PolicyConfig(seed=seed, rules=[rule]))


async def test_timeout_before_does_not_reach_upstream():
    up, inj = Counter(), injector("timeout")
    with pytest.raises(ToolTimeoutError):
        await inj.call("t", {}, up)
    assert up.calls == 0
    assert inj.events[0].fault == "timeout" and inj.events[0].detail == {"phase": "before"}
    assert inj.calls[0].ok is False


async def test_timeout_after_executes_side_effect_then_fails():
    up, inj = Counter(), injector("timeout", phase="after")
    with pytest.raises(ToolTimeoutError):
        await inj.call("t", {}, up)
    assert up.calls == 1  # the ambiguous write: it happened, the agent was told it didn't


async def test_rate_limit_carries_retry_after():
    up, inj = Counter(), injector("rate_limit", retry_after=2.5)
    with pytest.raises(RateLimitError) as e:
        await inj.call("t", {}, up)
    assert e.value.retry_after == 2.5 and "429" in str(e.value)
    assert up.calls == 0


async def test_fail_after_n():
    up, inj = Counter(), injector("fail_after", n=2)
    assert (await inj.call("t", {"x": 1}, up)) == {"ok": True, "x": 1}
    await inj.call("t", {}, up)
    for _ in range(3):
        with pytest.raises(UpstreamError) as e:
            await inj.call("t", {}, up)
        assert e.value.status == 503
    assert up.calls == 2
    assert [ev.call_index for ev in inj.events] == [2, 3, 4]


async def test_glob_and_call_indices_targeting():
    rules = [FaultRule(tools="search_*", fault="rate_limit", call_indices=[1])]
    inj, up = Injector(PolicyConfig(rules=rules)), Counter()
    await inj.call("search_docs", {}, up)  # index 0: not targeted
    with pytest.raises(RateLimitError):
        await inj.call("search_docs", {}, up)  # index 1: targeted
    await inj.call("create", {}, up)  # index 2: name doesn't match
    assert [e.call_index for e in inj.events] == [1]


async def test_rules_stack_outermost_first():
    rules = [FaultRule(fault="fail_after", params={"n": 0}), FaultRule(fault="rate_limit")]
    inj = Injector(PolicyConfig(rules=rules))
    with pytest.raises(UpstreamError):  # outer rule short-circuits before the inner one
        await inj.call("t", {}, Counter())
    assert [e.fault for e in inj.events] == ["fail_after"]


async def fault_sequence(seed: int, n: int = 200) -> list[int]:
    inj = injector("timeout", probability=0.3, seed=seed)
    for _ in range(n):
        with contextlib.suppress(ToolTimeoutError):
            await inj.call("t", {}, Counter())
    return [e.call_index for e in inj.events]


@pytest.mark.parametrize("fault", ["timeout", "rate_limit", "fail_after"])
async def test_every_fault_is_deterministic_under_seed(fault):
    async def seq(seed):
        inj = injector(fault, probability=0.5, seed=seed)
        out = []
        for i in range(50):
            try:
                await inj.call("t", {"i": i}, Counter())
                out.append("ok")
            except Exception as e:
                out.append(type(e).__name__)
        return out, [(e.call_index, e.detail) for e in inj.events]

    assert await seq(7) == await seq(7)


async def test_same_seed_same_sequence_different_seed_differs():
    a, b, c = await fault_sequence(1), await fault_sequence(1), await fault_sequence(2)
    assert a == b
    assert a != c
    assert 30 < len(a) < 90  # roughly p=0.3 of 200


async def test_decision_for_call_n_independent_of_earlier_calls():
    """Changing the args or tool of earlier calls must not shift later fault decisions."""
    rule = FaultRule(fault="timeout", probability=0.5)

    async def fired_at(prefix_tools):
        inj = Injector(PolicyConfig(seed=3, rules=[rule]))
        for i, tool in enumerate([*prefix_tools, "t", "t", "t"]):
            with contextlib.suppress(ToolTimeoutError):
                await inj.call(tool, {"i": i}, Counter())
        return {e.call_index for e in inj.events if e.call_index >= 2}

    assert await fired_at(["a", "b"]) == await fired_at(["x", "y"])


# --- Result-shaping faults -------------------------------------------------


async def ok_ticket(**kw):
    return {"id": "T-1", "title": "x", "assignee": None}


async def test_error_mid_task_fails_only_at_index():
    inj = injector("error_mid_task", at=1)
    await inj.call("t", {}, ok_ticket)
    with pytest.raises(UpstreamError) as e:
        await inj.call("t", {}, ok_ticket)
    assert e.value.status == 500
    await inj.call("t", {}, ok_ticket)
    assert [ev.call_index for ev in inj.events] == [1]


async def test_latency_delays_then_passes_through():
    inj = injector("latency", delay_s=0.01, jitter_s=0.01)
    assert await inj.call("t", {}, ok_ticket) == await ok_ticket()
    delay = inj.events[0].detail["delay_s"]
    assert 0.01 <= delay <= 0.02
    assert inj.calls[0].duration_ms >= 10


async def test_malformed_json_truncates_to_invalid_json():
    inj = injector("malformed_json")
    out = await inj.call("t", {}, ok_ticket)
    assert isinstance(out, RawText)
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert json.dumps(await ok_ticket()).startswith(out)


async def test_malformed_json_ignores_scalars():
    async def number(**kw):
        return 12

    inj = injector("malformed_json")
    assert await inj.call("t", {}, number) == 12
    assert inj.events == []


async def test_stale_data_replays_oldest_response_for_same_args():
    stock = iter([9, 4, 1])

    async def check(sku):
        return {"available": next(stock)}

    rules = [FaultRule(fault="stale_data", call_indices=[2])]
    inj = Injector(PolicyConfig(rules=rules))
    assert (await inj.call("check", {"sku": "w"}, check))["available"] == 9
    assert (await inj.call("check", {"sku": "w"}, check))["available"] == 4
    assert (await inj.call("check", {"sku": "w"}, check))["available"] == 9  # stale
    assert inj.events[0].detail == {"from_call": 0}


async def test_stale_data_without_history_passes_through():
    inj = injector("stale_data")
    await inj.call("check", {"sku": "w"}, ok_ticket)
    assert inj.events == []


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"field": "id"}, {"id_v2": "T-1", "title": "x", "assignee": None}),
        (
            {"field": "id", "rename_to": "ticketId"},
            {"ticketId": "T-1", "title": "x", "assignee": None},
        ),
        ({"field": "id", "mode": "drop"}, {"title": "x", "assignee": None}),
    ],
)
async def test_schema_drift(params, expected):
    inj = injector("schema_drift", **params)
    assert await inj.call("t", {}, ok_ticket) == expected


async def test_schema_drift_applies_to_every_object_in_a_list():
    async def many(**kw):
        return [{"id": 1}, {"id": 2}]

    inj = injector("schema_drift", field="id", mode="drop")
    assert await inj.call("t", {}, many) == [{}, {}]


@pytest.mark.parametrize("fault", ["malformed_json", "schema_drift", "latency"])
async def test_result_faults_are_deterministic(fault):
    async def details(seed):
        inj = injector(fault, seed=seed, **({"delay_s": 0} if fault == "latency" else {}))
        for _ in range(10):
            await inj.call("t", {}, ok_ticket)
        return [e.detail for e in inj.events]

    assert await details(5) == await details(5)


async def test_fault_events_carry_rule_index():
    rules = [FaultRule(tools="a", fault="rate_limit"), FaultRule(tools="b", fault="timeout")]
    inj = Injector(PolicyConfig(rules=rules))
    for tool in ("a", "b"):
        with contextlib.suppress(ToolFault):
            await inj.call(tool, {}, ok_ticket)
    assert [(e.fault, e.rule) for e in inj.events] == [("rate_limit", 0), ("timeout", 1)]
