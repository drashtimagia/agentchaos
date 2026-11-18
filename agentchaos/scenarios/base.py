"""Scenario interface: fresh fake server per run, a task prompt, and a state oracle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class ToolSpec:
    """A framework-neutral tool definition. Runners adapt this to their framework."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    fn: Callable[..., Awaitable[Any] | Any]


@dataclass
class OracleResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    """One step of a scenario's reference plan, used by the scripted agent.

    ``args`` may be a callable taking the results of earlier steps.
    """

    tool: str
    args: dict[str, Any] | Callable[[list[Any]], dict[str, Any]]


class FakeServer(ABC):
    """In-memory tool server. One instance per run; never shared."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """A deep copy of the full world state, for the oracle."""

    @abstractmethod
    def tools(self) -> list[ToolSpec]: ...


class Scenario(ABC):
    name: ClassVar[str]
    prompt: ClassVar[str]

    @abstractmethod
    def create_server(self) -> FakeServer:
        """Return a brand-new server with fresh state. Called once per run."""

    @abstractmethod
    def oracle(self, snapshot: dict[str, Any]) -> OracleResult:
        """Judge the final world state."""

    def reference_plan(self) -> list[Step]:
        """The happy-path tool calls; drives the scripted agent in tests."""
        raise NotImplementedError
