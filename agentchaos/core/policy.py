"""Policy loading and the per-run fault injector."""

from __future__ import annotations

import inspect
import random
import time
from collections.abc import Callable
from fnmatch import fnmatchcase
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from agentchaos.core import registry
from agentchaos.core.faults import CallNext, Fault, Response, ToolCallContext
from agentchaos.core.models import FaultEvent, FaultRule, PolicyConfig, ToolCall
from agentchaos.core.payload import is_error, jsonable

Sink = Callable[[ToolCall | FaultEvent], None]


def load_policy(source: str | Path | dict[str, Any]) -> PolicyConfig:
    """Load and validate a policy from a YAML path or a dict. Fails fast on bad rules.

    ``profile: <name>`` is an include: the profile's rules are placed before the
    policy's own rules and the returned policy has ``profile`` cleared, so a
    loaded policy is always fully resolved and safe to serialize and reload.
    """
    data = source if isinstance(source, dict) else yaml.safe_load(Path(source).read_text())
    policy = PolicyConfig.model_validate(data or {})
    if policy.profile:
        base = load_policy(profile_data(policy.profile))
        policy = policy.model_copy(update={"profile": None, "rules": base.rules + policy.rules})
    for rule in policy.rules:
        build_fault(rule)  # surface unknown faults / bad params at load time
    return policy


def profiles() -> list[str]:
    files = resources.files("agentchaos.profiles").iterdir()
    return sorted(f.name.removesuffix(".yaml") for f in files if f.name.endswith(".yaml"))


def profile_data(name: str) -> dict[str, Any]:
    if name not in profiles():
        raise KeyError(f"Unknown profile '{name}'. Available: {', '.join(profiles())}")
    text = resources.files("agentchaos.profiles").joinpath(f"{name}.yaml").read_text()
    return yaml.safe_load(text)


def pin_to_events(policy: PolicyConfig, events: list[FaultEvent]) -> PolicyConfig:
    """A policy where each rule fires exactly on the calls it fired on in ``events``.

    Used by replay: with the same seed, each fault also gets the same RNG, so
    fault details (truncation points, chosen fields) match too.
    """
    rules = [
        rule.model_copy(
            update={
                "probability": 1.0,
                "call_indices": sorted({e.call_index for e in events if e.rule == i}),
            }
        )
        for i, rule in enumerate(policy.rules)
    ]
    return policy.model_copy(update={"rules": rules})


def build_fault(rule: FaultRule) -> Fault:
    cls = registry.get_fault(rule.fault)
    try:
        return cls(**rule.params)
    except TypeError as e:
        raise ValueError(f"Invalid params for fault '{rule.fault}': {e}") from None


def call_rng(seed: int, call_index: int, rule_index: int) -> random.Random:
    """RNG for one (call, rule) pair.

    Derived from the run seed and the call's position rather than drawn from a
    shared stream, so the decision for call N never depends on how many random
    numbers earlier calls consumed. String seeds are hashed with SHA-512 by
    ``random.Random``, so this is stable across processes and platforms.
    """
    return random.Random(f"{seed}:{call_index}:{rule_index}")


class Injector:
    """Applies a policy to the tool calls of exactly one run.

    Holds that run's call counter and trace; create a new one per run.
    """

    def __init__(self, policy: PolicyConfig, seed: int | None = None, sink: Sink | None = None):
        self.policy = policy
        self.seed = policy.seed if seed is None else seed
        self.sink = sink
        self._faults = [(i, rule, build_fault(rule)) for i, rule in enumerate(policy.rules)]
        self._next_index = 0
        self._history: list[Response] = []
        self.calls: list[ToolCall] = []
        self.events: list[FaultEvent] = []

    def _active(self, tool: str, index: int) -> list[tuple[int, Fault, random.Random]]:
        active = []
        for i, rule, fault in self._faults:
            if not fnmatchcase(tool, rule.tools):
                continue
            if rule.call_indices is not None and index not in rule.call_indices:
                continue
            rng = call_rng(self.seed, index, i)
            if rng.random() < rule.probability:
                active.append((i, fault, rng))
        return active

    async def call(self, tool: str, args: dict[str, Any], fn: Callable[..., Any]) -> Any:
        """Run ``fn(**args)`` through every matching fault. Records the call either way."""
        index = self._next_index  # reserved up front: parallel calls get distinct indices
        self._next_index += 1
        fired: list[tuple[str, int, dict[str, Any]]] = []
        history = tuple(self._history)

        async def upstream() -> Any:
            result = fn(**args)
            return await result if inspect.isawaitable(result) else result

        call_next = upstream
        for rule, fault, rng in reversed(self._active(tool, index)):
            ctx = ToolCallContext(tool, args, index, rng, rule, history, fired)
            call_next = _bind(fault, ctx, call_next)

        start = time.perf_counter()
        try:
            result = await call_next()
        except Exception as e:
            self._record(index, tool, args, fired, start, error=f"{type(e).__name__}: {e}")
            raise
        if not is_error(result):
            self._history.append(Response(index, tool, args, result))
        self._record(index, tool, args, fired, start, result=result)
        return result

    def _record(
        self,
        index: int,
        tool: str,
        args: dict[str, Any],
        fired: list[tuple[str, int, dict[str, Any]]],
        start: float,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        call = ToolCall(
            index=index,
            tool=tool,
            args=args,
            ok=error is None and not is_error(result),
            result=jsonable(result),
            error=error,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        events = [
            FaultEvent(call_index=index, tool=tool, fault=name, rule=rule, detail=detail)
            for name, rule, detail in fired
        ]
        self.calls.append(call)
        self.events.extend(events)
        if self.sink:
            for item in [call, *events]:
                self.sink(item)


def _bind(fault: Fault, ctx: ToolCallContext, call_next: CallNext) -> CallNext:
    async def wrapped() -> Any:
        return await fault.apply(ctx, call_next)

    return wrapped
