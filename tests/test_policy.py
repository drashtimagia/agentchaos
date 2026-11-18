import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentchaos.core import registry
from agentchaos.core.faults import FailAfter, RateLimit, Timeout
from agentchaos.core.models import PolicyConfig
from agentchaos.core.policy import load_policy, profiles

ROOT = Path(__file__).parent.parent


def test_load_yaml(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(
        """
schema_version: 1
seed: 42
rules:
  - tools: "search_*"
    fault: rate_limit
    probability: 0.25
    params: {retry_after: 5}
  - fault: fail_after
    call_indices: [3, 4]
    params: {n: 3}
"""
    )
    pol = load_policy(p)
    assert pol.seed == 42
    assert pol.rules[0].tools == "search_*" and pol.rules[0].params == {"retry_after": 5}
    assert pol.rules[1].tools == "*" and pol.rules[1].call_indices == [3, 4]


def test_empty_policy_is_valid():
    assert load_policy({}).rules == []


def test_profile_rules_come_first_and_policy_is_resolved():
    pol = load_policy({"profile": "rate-limited", "rules": [{"fault": "timeout"}]})
    assert [r.fault for r in pol.rules] == ["rate_limit", "timeout"]
    assert pol.profile is None
    assert load_policy(pol.model_dump()) == pol  # reloading never re-applies the profile


@pytest.mark.parametrize("name", profiles())
def test_builtin_profiles_load(name):
    assert load_policy({"profile": name}).rules


def test_unknown_profile_rejected():
    with pytest.raises(KeyError, match="Unknown profile 'nope'"):
        load_policy({"profile": "nope"})


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 2},
        {"rules": [{"fault": "timeout", "probability": 1.5}]},
        {"rules": [{"fault": "timeout", "typo_field": 1}]},
        {"unknown_top_level": True},
    ],
)
def test_schema_violations_rejected(bad):
    with pytest.raises(ValidationError):
        load_policy(bad)


def test_unknown_fault_rejected_at_load():
    with pytest.raises(KeyError, match="Unknown fault 'nope'"):
        load_policy({"rules": [{"fault": "nope"}]})


def test_bad_fault_params_rejected_at_load():
    with pytest.raises(ValueError, match="Invalid params for fault 'timeout'"):
        load_policy({"rules": [{"fault": "timeout", "params": {"bogus": 1}}]})


def test_builtins_discovered_via_entry_points():
    found = registry._discover(registry.FAULTS_GROUP)
    assert found["timeout"] is Timeout
    assert found["rate_limit"] is RateLimit
    assert found["fail_after"] is FailAfter


def test_published_schema_matches_model():
    published = json.loads((ROOT / "schemas" / "policy.v1.schema.json").read_text())
    assert published == PolicyConfig.model_json_schema(), "run: agentchaos schema"
