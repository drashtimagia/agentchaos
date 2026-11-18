import json
from pathlib import Path

import mcp_types as types
import pytest

from agentchaos.core.models import FaultRule, PolicyConfig, TraceRecord
from agentchaos.core.payload import RawText, get_data, jsonable, with_data, with_text
from agentchaos.core.policy import pin_to_events
from agentchaos.core.recorder import Recorder, find_run, read_trace
from agentchaos.execution import policy_for, replay, run_experiment, run_trial
from agentchaos.runners.scripted import ScriptedAgent
from agentchaos.scenarios.tasks.ticketing import TicketingScenario
from agentchaos.scoring.oracles import KeywordJudge

ROOT = Path(__file__).parent.parent
scen = TicketingScenario()


def agent():
    return ScriptedAgent(scen.reference_plan())


async def test_trace_records_every_event_in_order(tmp_path):
    path = tmp_path / "t.jsonl"
    with Recorder(path) as rec:
        run = await run_trial(
            scen, agent(), policy_for("timeout", 1.0), fault_class="timeout", seed=1, recorder=rec
        )
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(line["schema_version"] == 1 and line["run_id"] == run.run_id for line in lines)
    types_ = [line["type"] for line in lines]
    assert types_[0] == "run_start" and types_[-1] == "outcome"
    assert types_.count("tool_call") == len(run.calls)
    assert types_.count("fault") == len(run.faults)


async def test_trace_is_flushed_as_it_is_written(tmp_path):
    path = tmp_path / "t.jsonl"
    rec = Recorder(path)
    await run_trial(scen, agent(), policy_for("clean"), fault_class="clean", seed=1, recorder=rec)
    assert len(path.read_text().splitlines()) == 4  # visible before close()
    rec.close()


async def test_concurrent_runs_interleave_and_separate_by_run_id(tmp_path):
    path = tmp_path / "t.jsonl"
    with Recorder(path) as rec:
        runs = await run_experiment(
            scen, agent, {"timeout": policy_for("timeout")}, trials=6, concurrency=6, recorder=rec
        )
    for run in runs:
        found = find_run(run.run_id, [path])
        assert found.start.seed == run.seed
        assert [c.index for c in found.calls] == [c.index for c in run.calls]
        assert found.outcome and found.outcome.task_success == run.outcome.task_success


def test_find_run_missing(tmp_path):
    (tmp_path / "t.jsonl").write_text("")
    with pytest.raises(KeyError):
        find_run("nope", [tmp_path / "t.jsonl"])


@pytest.mark.parametrize("fault", ["timeout", "rate_limit", "malformed_json", "schema_drift"])
async def test_replay_reproduces_fault_sequence(tmp_path, fault):
    path = tmp_path / "t.jsonl"
    with Recorder(path) as rec:
        original = await run_trial(
            scen, agent(), policy_for(fault, 0.5), fault_class=fault, seed=77, recorder=rec
        )
    again = await replay(find_run(original.run_id, [path]))

    def sig(run):
        return [(e.call_index, e.fault, e.rule, e.detail) for e in run.faults]

    assert sig(again) == sig(original)
    assert again.outcome.task_success == original.outcome.task_success


def test_pin_to_events_fires_only_where_recorded():
    policy = PolicyConfig(rules=[FaultRule(fault="timeout", probability=0.3)] * 2)
    from agentchaos.core.models import FaultEvent

    events = [FaultEvent(call_index=i, tool="t", fault="timeout", rule=1) for i in (2, 5)]
    pinned = pin_to_events(policy, events)
    assert [(r.probability, r.call_indices) for r in pinned.rules] == [(1.0, []), (1.0, [2, 5])]


async def test_hallucinated_success_flagged():
    pol = policy_for("timeout", 1.0, phase="after")
    pol.rules[0].call_indices = [0]
    run = await run_trial(scen, agent(), pol, fault_class="t", seed=1, judge=KeywordJudge())
    assert run.outcome.claim == "claims_success"  # the scripted agent said "Done."
    assert run.outcome.safety_violations == ["duplicate_write", "hallucinated_success"]


async def test_graceful_surrender_is_not_a_violation():
    run = await run_trial(
        scen, agent(), policy_for("fail_after"), fault_class="f", seed=1, judge=KeywordJudge()
    )
    assert run.outcome.claim == "reports_failure"
    assert run.outcome.safety_violations == []


@pytest.mark.parametrize(
    "message,claim",
    [
        ("Done. Ticket T-1 created and assigned to bob.", "claims_success"),
        ("I couldn't assign the ticket because the service kept failing.", "reports_failure"),
        ("Here is what I found.", "unclear"),
    ],
)
async def test_keyword_judge(message, claim):
    assert await KeywordJudge().classify("task", message) == claim


def test_payload_helpers_on_mcp_results():
    result = types.CallToolResult(content=[types.TextContent(type="text", text='{"a": 1}')])
    assert get_data(result) == {"a": 1}
    assert get_data(with_data(result, {"b": 2})) == {"b": 2}
    broken = with_text(result, '{"a"')
    with pytest.raises(ValueError):
        get_data(broken)
    assert jsonable(result)["content"][0]["text"] == '{"a": 1}'
    error = types.CallToolResult(
        content=[types.TextContent(type="text", text="boom")], is_error=True
    )
    with pytest.raises(ValueError):
        get_data(error)


def test_payload_helpers_on_python_values():
    assert get_data({"a": 1}) == {"a": 1}
    assert isinstance(with_text({"a": 1}, "{"), RawText)


def test_published_trace_schema_matches_model():
    from pydantic import TypeAdapter

    published = json.loads((ROOT / "schemas" / "trace.v1.schema.json").read_text())
    assert published == TypeAdapter(TraceRecord).json_schema(), "run: agentchaos schema"


async def test_read_trace_roundtrip(tmp_path):
    path = tmp_path / "t.jsonl"
    with Recorder(path) as rec:
        await run_trial(scen, agent(), policy_for("clean"), fault_class="c", seed=1, recorder=rec)
    assert [r.type for r in read_trace(path)] == ["run_start", "tool_call", "tool_call", "outcome"]
