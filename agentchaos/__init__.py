"""AgentChaos: chaos engineering for AI agents."""

__version__ = "0.1.0"

from agentchaos.core import decorator as chaos
from agentchaos.core.faults import (
    FailAfter,
    Fault,
    RateLimit,
    RateLimitError,
    Timeout,
    ToolFault,
    ToolTimeoutError,
    UpstreamError,
)
from agentchaos.core.models import SCHEMA_VERSION, PolicyConfig
from agentchaos.core.policy import Injector, load_policy

__all__ = [
    "SCHEMA_VERSION",
    "FailAfter",
    "Fault",
    "Injector",
    "PolicyConfig",
    "RateLimit",
    "RateLimitError",
    "Timeout",
    "ToolFault",
    "ToolTimeoutError",
    "UpstreamError",
    "chaos",
    "load_policy",
]
