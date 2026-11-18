import pytest

from agentchaos.execution import policy_for, run_trial
from agentchaos.runners.scripted import ScriptedAgent
from agentchaos.scenarios.tasks.ticketing import ASSIGNEE, TITLE, TicketingScenario

scen = TicketingScenario()


def test_oracle_passes_on_exactly_one_correct_ticket():
    s = scen.create_server()
    t = s.create_ticket(TITLE, priority="high")
    s.assign_ticket(t["id"], ASSIGNEE)
    assert scen.oracle(s.snapshot()).passed


def test_oracle_normalizes_title():
    s = scen.create_server()
    t = s.create_ticket("  login page returns 500 on submit.", priority="high")
    s.assign_ticket(t["id"], ASSIGNEE)
    assert scen.oracle(s.snapshot()).passed


@pytest.mark.parametrize(
    "setup,violations",
    [
        (lambda s: None, []),  # nothing created
        (lambda s: s.create_ticket(TITLE, priority="high"), []),  # unassigned
        (lambda s: s.assign_ticket(s.create_ticket(TITLE)["id"], ASSIGNEE), []),  # wrong priority
        (
            lambda s: [
                s.assign_ticket(s.create_ticket(TITLE, priority="high")["id"], ASSIGNEE)
                for _ in range(2)
            ],
            ["duplicate_write"],
        ),
    ],
)
def test_oracle_failures(setup, violations):
    s = scen.create_server()
    setup(s)
    r = scen.oracle(s.snapshot())
    assert not r.passed
    assert r.violations == violations


def test_server_rejects_bad_input():
    s = scen.create_server()
    with pytest.raises(ValueError):
        s.assign_ticket("T-99", "bob")
    with pytest.raises(ValueError):
        s.create_ticket("x", priority="urgent")


def test_snapshot_is_a_copy():
    s = scen.create_server()
    snap = s.snapshot()
    s.create_ticket("x")
    assert snap["tickets"] == {}


async def test_scripted_agent_clean_run_succeeds():
    run = await run_trial(scen, ScriptedAgent(scen.reference_plan()), policy_for("clean"),
                          fault_class="clean", seed=1)  # fmt: skip
    assert run.outcome.task_success and not run.faults
    assert [c.tool for c in run.calls] == ["create_ticket", "assign_ticket"]


async def test_timeout_after_write_causes_duplicate_on_naive_retry():
    pol = policy_for("timeout", probability=1.0, phase="after")
    pol.rules[0].call_indices = [0]  # only the first create times out
    run = await run_trial(scen, ScriptedAgent(scen.reference_plan()), pol,
                          fault_class="timeout", seed=1)  # fmt: skip
    assert not run.outcome.task_success
    assert run.outcome.safety_violations == ["duplicate_write"]


async def test_permanent_failure_yields_surrender_message():
    run = await run_trial(scen, ScriptedAgent(scen.reference_plan()), policy_for("fail_after"),
                          fault_class="fail_after", seed=1)  # fmt: skip
    assert not run.outcome.task_success
    assert "could not complete" in run.outcome.final_message
