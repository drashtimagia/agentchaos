"""pytest plugin: ``agentchaos.pytest_plugin``.

Provides the ``chaos_policy`` fixture and the ``@pytest.mark.chaos`` marker.
Install via the ``pytest`` extra (``pip install 'agentchaos[pytest]'``), or
register manually in conftest.py:

    pytest_plugins = ["agentchaos.pytest_plugin"]

Marker usage
------------
    @pytest.mark.chaos(profile="flaky-network", trials=5, seed=42)
    async def test_my_agent_survives(chaos_policy):
        result = await my_agent.run(chaos_policy)
        assert result.success

Fixture
-------
``chaos_policy`` — a ``PolicyConfig`` built from the marker parameters, or an
empty policy when the test is not marked.  Pass it to ``run_trial`` or
``run_experiment`` directly, or activate the injector yourself.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentchaos.core.models import PolicyConfig
from agentchaos.core.policy import load_policy


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "chaos(profile=None, faults=None, probability=None, seed=None, trials=1): "
        "run this test under AgentChaos fault injection.",
    )


@pytest.fixture
def chaos_policy(request: pytest.FixtureRequest) -> PolicyConfig:
    """Return a PolicyConfig built from the ``@pytest.mark.chaos`` marker.

    When the test has no marker an empty policy is returned (no faults injected).
    """
    marker = request.node.get_closest_marker("chaos")
    if marker is None:
        return PolicyConfig()

    kwargs: dict[str, Any] = marker.kwargs
    profile: str | None = kwargs.get("profile")
    faults: str | None = kwargs.get("faults")
    probability: float | None = kwargs.get("probability")
    seed: int | None = kwargs.get("seed")

    spec: dict[str, Any] = {}
    if profile:
        spec["profile"] = profile
    if faults:
        from agentchaos.core import registry
        from agentchaos.core.models import FaultRule

        rules = []
        for name in (f.strip() for f in faults.split(",") if f.strip()):
            cls = registry.get_fault(name)
            p = cls.default_probability if probability is None else probability
            rules.append(FaultRule(fault=name, probability=p))
        spec["rules"] = [r.model_dump() for r in rules]
    if seed is not None:
        spec["seed"] = seed

    return load_policy(spec) if spec else PolicyConfig()


@pytest.fixture
def chaos_injector(chaos_policy: PolicyConfig):
    """An ``Injector`` already activated for the test.

    Wraps tools decorated with ``@chaos.tool`` automatically — no other setup
    needed.  The injector is deactivated after the test.
    """
    from agentchaos.core import decorator
    from agentchaos.core.policy import Injector

    injector = Injector(chaos_policy)
    with decorator.activate(injector):
        yield injector
