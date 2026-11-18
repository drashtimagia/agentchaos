"""Custom fault: Slack-style rate limit with Retry-After."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentchaos.core.faults import Fault, ToolCallContext, ToolFault


@dataclass
class SlackRateLimit(Fault):
    """Raise a 429 that embeds a ``Retry-After`` value in the message.

    This models Slack's Tier-1 rate limit: the call is blocked entirely
    before it reaches the upstream, so no side effects occur.
    """

    retry_after: int = 60
    default_probability: float = field(default=0.3, init=False, repr=False)

    async def apply(self, ctx: ToolCallContext, call_next):
        rng = ctx.rng
        if rng.random() >= self.default_probability:
            return await call_next(ctx)
        raise ToolFault(
            f"429 Too Many Requests — Retry-After: {self.retry_after}s "
            f"(Slack rate limit on '{ctx.tool}')"
        )
