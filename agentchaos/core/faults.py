"""Fault base class, tool-call context, and built-in faults.

A fault is async middleware around a tool call::

    async def apply(self, ctx, call_next) -> Any

It may delay, raise, or rewrite the result, and must report what it did with
``ctx.fire(...)`` so the run trace records it. All randomness must come from
``ctx.rng`` so behaviour is a pure function of the seed.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

CallNext = Callable[[], Awaitable[Any]]


class ToolFault(Exception):
    """Base class for errors injected by AgentChaos. Agents see these as tool errors."""

    kind: ClassVar[str] = "error"


class ToolTimeoutError(ToolFault):
    kind = "timeout"


class RateLimitError(ToolFault):
    kind = "rate_limit"

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests: retry after {retry_after:g}s")
        self.retry_after = retry_after


class UpstreamError(ToolFault):
    kind = "upstream_error"

    def __init__(self, status: int, message: str):
        super().__init__(f"{status} {message}")
        self.status = status


@dataclass
class ToolCallContext:
    """Everything a fault may look at. ``rng`` is derived from (seed, call, rule)."""

    tool: str
    args: dict[str, Any]
    call_index: int
    rng: random.Random
    run_id: str = ""
    fired: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def fire(self, fault: str, **detail: Any) -> None:
        self.fired.append((fault, detail))


class Fault:
    """Base class. Subclasses are dataclasses whose fields are the fault params."""

    name: ClassVar[str]
    #: Rule defaults used when a fault class is selected by name on the CLI.
    default_probability: ClassVar[float] = 0.5

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        raise NotImplementedError


@dataclass
class Timeout(Fault):
    """The call times out.

    ``phase="before"``: the upstream never sees the call.
    ``phase="after"``: the upstream executes (side effects happen) but the agent
    still gets a timeout, the classic ambiguous-write case.
    """

    name: ClassVar[str] = "timeout"
    phase: Literal["before", "after"] = "before"
    delay_s: float = 0.0

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        if self.phase == "after":
            await call_next()
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        ctx.fire(self.name, phase=self.phase)
        raise ToolTimeoutError(f"Tool '{ctx.tool}' timed out")


@dataclass
class RateLimit(Fault):
    """HTTP 429 with a Retry-After hint; the upstream is not called."""

    name: ClassVar[str] = "rate_limit"
    retry_after: float = 1.0

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        ctx.fire(self.name, retry_after=self.retry_after)
        raise RateLimitError(self.retry_after)


@dataclass
class FailAfter(Fault):
    """The first ``n`` calls of the run succeed, every later matching call fails with 503."""

    name: ClassVar[str] = "fail_after"
    default_probability: ClassVar[float] = 1.0
    n: int = 1
    status: int = 503

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        if ctx.call_index < self.n:
            return await call_next()
        ctx.fire(self.name, n=self.n, status=self.status)
        raise UpstreamError(self.status, "Service Unavailable")
