"""Fault base class, tool-call context, and built-in faults.

A fault is async middleware around a tool call::

    async def apply(self, ctx, call_next) -> Any

It may delay, raise, or rewrite the result, and must report what it did with
``ctx.fire(...)`` so the run trace records it. All randomness must come from
``ctx.rng`` so behaviour is a pure function of the seed. Faults that rewrite
results use ``agentchaos.core.payload`` so they work in-process and over MCP.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from agentchaos.core.payload import get_data, with_data, with_text

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


@dataclass(frozen=True)
class Response:
    """A successful earlier call in the same run, as the agent received it."""

    index: int
    tool: str
    args: dict[str, Any]
    result: Any


@dataclass
class ToolCallContext:
    """Everything a fault may look at. ``rng`` is derived from (seed, call, rule)."""

    tool: str
    args: dict[str, Any]
    call_index: int
    rng: random.Random
    rule: int = 0
    history: Sequence[Response] = ()
    fired: list[tuple[str, int, dict[str, Any]]] = field(default_factory=list)

    def fire(self, fault: str, **detail: Any) -> None:
        self.fired.append((fault, self.rule, detail))


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


@dataclass
class ErrorMidTask(Fault):
    """HTTP 500 on exactly one call index."""

    name: ClassVar[str] = "error_mid_task"
    default_probability: ClassVar[float] = 1.0
    at: int = 1
    status: int = 500

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        if ctx.call_index != self.at:
            return await call_next()
        ctx.fire(self.name, at=self.at, status=self.status)
        raise UpstreamError(self.status, "Internal Server Error")


@dataclass
class Latency(Fault):
    """Delay the call by ``delay_s`` plus up to ``jitter_s``, then let it through."""

    name: ClassVar[str] = "latency"
    delay_s: float = 0.2
    jitter_s: float = 0.0

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        delay = self.delay_s + ctx.rng.uniform(0, self.jitter_s)
        ctx.fire(self.name, delay_s=round(delay, 4))
        await asyncio.sleep(delay)
        return await call_next()


@dataclass
class MalformedJSON(Fault):
    """Truncate a JSON object or array response at a seeded position.

    Any proper prefix of a serialized object or array is invalid JSON, so the
    agent always receives something unparseable. Scalar and non-JSON responses
    pass through untouched.
    """

    name: ClassVar[str] = "malformed_json"

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        result = await call_next()
        try:
            data = get_data(result)
        except ValueError:
            return result
        if not isinstance(data, dict | list):
            return result
        text = json.dumps(data)
        cut = ctx.rng.randrange(1, len(text))
        ctx.fire(self.name, cut=cut, length=len(text))
        return with_text(result, text[:cut])


@dataclass
class StaleData(Fault):
    """Return the oldest earlier response to the same tool and arguments.

    The upstream is not called. If there is no earlier response, the call goes
    through normally and nothing fires.
    """

    name: ClassVar[str] = "stale_data"

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        for prev in ctx.history:
            if prev.tool == ctx.tool and prev.args == ctx.args:
                ctx.fire(self.name, from_call=prev.index)
                return prev.result
        return await call_next()


@dataclass
class SchemaDrift(Fault):
    """Rename or drop one field in an object response (or in every object of a list).

    ``field`` picks the field; otherwise one is chosen with the seeded RNG.
    Renamed fields get ``rename_to``, defaulting to ``<field>_v2``.
    """

    name: ClassVar[str] = "schema_drift"
    mode: Literal["rename", "drop"] = "rename"
    field: str | None = None
    rename_to: str | None = None

    async def apply(self, ctx: ToolCallContext, call_next: CallNext) -> Any:
        result = await call_next()
        try:
            data = get_data(result)
        except ValueError:
            return result
        rows = data if isinstance(data, list) else [data]
        keys = sorted({k for row in rows if isinstance(row, dict) for k in row})
        key = self.field or (ctx.rng.choice(keys) if keys else None)
        if key not in keys:
            return result
        new_key = self.rename_to or f"{key}_v2"
        drifted = [_drift(row, key, new_key, self.mode) for row in rows]
        ctx.fire(self.name, mode=self.mode, field=key, to=None if self.mode == "drop" else new_key)
        return with_data(result, drifted if isinstance(data, list) else drifted[0])


def _drift(row: Any, key: str, new_key: str, mode: str) -> Any:
    if not isinstance(row, dict) or key not in row:
        return row
    if mode == "drop":
        return {k: v for k, v in row.items() if k != key}
    return {(new_key if k == key else k): v for k, v in row.items()}
