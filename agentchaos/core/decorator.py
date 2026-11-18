"""``@chaos.tool``: fault injection for plain Python function tools.

    from agentchaos import chaos

    @chaos.tool
    async def search(query: str) -> list[str]: ...

    with chaos.activate(injector):
        await search("bugs")   # goes through the injector's faults

Outside ``chaos.activate`` the tool behaves exactly like the undecorated
function. The active injector lives in a ``ContextVar``, so concurrent runs in
separate asyncio tasks never see each other's injector.

Decorated tools are always ``async`` (faults are async middleware), even when
the wrapped function is sync.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from agentchaos.core.policy import Injector

_active: ContextVar[Injector | None] = ContextVar("agentchaos_injector", default=None)


def current() -> Injector | None:
    return _active.get()


@contextmanager
def activate(injector: Injector) -> Iterator[Injector]:
    token = _active.set(injector)
    try:
        yield injector
    finally:
        _active.reset(token)


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Decorate a function tool. Usable as ``@chaos.tool`` or ``@chaos.tool(name=...)``."""

    def decorate(f: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or f.__name__
        sig = inspect.signature(f)

        @functools.wraps(f)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call_args = dict(bound.arguments)
            injector = _active.get()
            if injector is None:
                result = f(**call_args)
                return await result if inspect.isawaitable(result) else result
            return await injector.call(tool_name, call_args, f)

        wrapper.__agentchaos_tool__ = tool_name  # type: ignore[attr-defined]
        return wrapper

    return decorate(fn) if fn is not None else decorate


class _Chaos:
    """Namespace exported as ``agentchaos.chaos``."""

    tool = staticmethod(tool)
    activate = staticmethod(activate)
    current = staticmethod(current)


chaos = _Chaos()
