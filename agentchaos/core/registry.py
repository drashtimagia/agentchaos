"""Entry-point discovery for faults and scenarios.

Built-ins are registered in this package's own ``pyproject.toml`` under the same
``agentchaos.faults`` / ``agentchaos.scenarios`` groups third parties use, so
there is exactly one discovery path.
"""

from __future__ import annotations

from functools import cache
from importlib.metadata import entry_points
from typing import Any

FAULTS_GROUP = "agentchaos.faults"
SCENARIOS_GROUP = "agentchaos.scenarios"

# Runtime registrations (tests, notebooks) layered over entry points.
_extra: dict[str, dict[str, Any]] = {FAULTS_GROUP: {}, SCENARIOS_GROUP: {}}


@cache
def _discover(group: str) -> dict[str, Any]:
    return {ep.name: ep.load() for ep in entry_points(group=group)}


def _lookup(group: str) -> dict[str, Any]:
    return {**_discover(group), **_extra[group]}


def register_fault(cls: Any) -> Any:
    """Register a fault class at runtime. Usable as a decorator."""
    _extra[FAULTS_GROUP][cls.name] = cls
    return cls


def register_scenario(cls: Any) -> Any:
    _extra[SCENARIOS_GROUP][cls.name] = cls
    return cls


def faults() -> dict[str, Any]:
    return _lookup(FAULTS_GROUP)


def scenarios() -> dict[str, Any]:
    return _lookup(SCENARIOS_GROUP)


def get_fault(name: str) -> Any:
    try:
        return faults()[name]
    except KeyError:
        raise KeyError(
            f"Unknown fault '{name}'. Available: {', '.join(sorted(faults()))}"
        ) from None


def get_scenario(name: str) -> Any:
    try:
        return scenarios()[name]
    except KeyError:
        known = ", ".join(sorted(scenarios()))
        raise KeyError(f"Unknown scenario '{name}'. Available: {known}") from None
