import pytest

from agentchaos.core import registry
from agentchaos.core.models import FaultRule, PolicyConfig
from agentchaos.core.policy import load_policy
from agentchaos.execution import policy_for, run_trial
from agentchaos.runners.scripted import ScriptedAgent

ALL = sorted(registry.scenarios())


async def run(name, policy, seed=1):
    scen = registry.get_scenario(name)()
    return await run_trial(
        scen, ScriptedAgent(scen.reference_plan()), policy, fault_class="x", seed=seed
    )


def test_all_scenarios_registered():
    assert ALL == ["bank_transfer", "file_edit", "inventory", "search_summarize", "ticketing"]


@pytest.mark.parametrize("name", ALL)
async def test_reference_plan_passes_clean(name):
    r = await run(name, policy_for("clean"))
    assert r.outcome.task_success, r.outcome
    assert r.outcome.safety_violations == []


@pytest.mark.parametrize("name", ALL)
def test_untouched_world_fails_oracle_safely(name):
    scen = registry.get_scenario(name)()
    verdict = scen.oracle(scen.create_server().snapshot())
    assert not verdict.passed and verdict.violations == []


@pytest.mark.parametrize("name", ALL)
def test_servers_are_fresh_per_run(name):
    scen = registry.get_scenario(name)()
    a, b = scen.create_server(), scen.create_server()
    assert a is not b and a.snapshot() == b.snapshot()


def write_timeout_then_retry(tool):
    return PolicyConfig(
        rules=[FaultRule(tools=tool, fault="timeout", call_indices=[0], params={"phase": "after"})]
    )


async def test_bank_idempotency_key_prevents_double_transfer():
    r = await run("bank_transfer", write_timeout_then_retry("transfer"))
    assert r.outcome.task_success
    assert r.outcome.details["balances"] == {"checking": 800, "savings": 700}


async def test_bank_detects_double_transfer_without_key():
    from agentchaos.scenarios.tasks.bank_transfer import BankTransferScenario

    scen = BankTransferScenario()
    s = scen.create_server()
    s.transfer("checking", "savings", 200)
    s.transfer("checking", "savings", 200)
    assert scen.oracle(s.snapshot()).violations == ["duplicate_write"]


async def test_file_edit_partial_write_detected():
    r = await run("file_edit", policy_for("fail_after", n=3))  # 2 files' read+write ok
    assert not r.outcome.task_success
    assert r.outcome.safety_violations == ["partial_write"]


async def test_file_edit_corruption_detected():
    from agentchaos.scenarios.tasks.file_edit import FileEditScenario

    scen = FileEditScenario()
    s = scen.create_server()
    s.write_file("config/app.yaml", "garbage")
    assert "corrupted_write" in scen.oracle(s.snapshot()).violations


async def test_inventory_stale_stock_causes_oversell():
    pol = load_policy({"rules": [{"tools": "check_*", "fault": "stale_data"}]})
    r = await run("inventory", pol)
    assert r.outcome.details["orders"] == ["ana", "ben"]
    assert r.outcome.safety_violations == ["stale_data_order"]


async def test_inventory_fresh_stock_serves_only_ana():
    r = await run("inventory", policy_for("clean"))
    assert r.outcome.details == {"orders": ["ana"], "stock": 4}


async def test_search_schema_drift_makes_scripted_agent_surrender():
    pol = policy_for("schema_drift", 1.0, field="id")
    r = await run("search_summarize", pol)
    assert not r.outcome.task_success
    assert "could not complete" in r.outcome.final_message


async def test_search_fabricated_reference_detected():
    from agentchaos.scenarios.tasks.search_summarize import SearchSummarizeScenario

    scen = SearchSummarizeScenario()
    s = scen.create_server()
    s.submit_summary("...", ["D-101", "D-999"])
    assert scen.oracle(s.snapshot()).violations == ["fabricated_reference"]
