"""Versioned data models shared by every part of AgentChaos.

Every persisted format carries ``schema_version`` so files written today stay
readable after the format evolves. Bump ``SCHEMA_VERSION`` only with a
migration path and a DESIGN.md entry.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaultRule(_Model):
    """One policy rule: which calls to target and which fault to inject."""

    tools: str = Field("*", description="Glob matched against the tool name.")
    fault: str = Field(description="Registered fault name, e.g. 'timeout'.")
    probability: float = Field(1.0, ge=0.0, le=1.0)
    call_indices: list[int] | None = Field(
        None, description="Only apply on these 0-based call indices within the run."
    )
    params: dict[str, Any] = Field(default_factory=dict)


class PolicyConfig(_Model):
    """A fault-injection policy, loaded from YAML."""

    schema_version: Literal[1] = SCHEMA_VERSION
    seed: int = 0
    profile: str | None = None
    rules: list[FaultRule] = Field(default_factory=list)


class FaultEvent(_Model):
    """A fault that actually fired on a tool call."""

    call_index: int
    tool: str
    fault: str
    rule: int = Field(description="Index of the policy rule that fired.")
    detail: dict[str, Any] = Field(default_factory=dict)


class ToolCall(_Model):
    """One tool call as the agent experienced it (after faults)."""

    index: int
    tool: str
    args: dict[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: float


Claim = Literal["claims_success", "reports_failure", "unclear"]


class Outcome(_Model):
    """How a run ended, judged by the scenario oracle."""

    task_success: bool
    safety_violations: list[str] = Field(default_factory=list)
    final_message: str = ""
    claim: Claim | None = Field(
        None, description="What the final message says happened; None if not judged."
    )
    agent_error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Usage(_Model):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class Run(_Model):
    """A single isolated trial: one scenario, one policy, one seed."""

    schema_version: Literal[1] = SCHEMA_VERSION
    run_id: str
    scenario: str
    fault_class: str
    seed: int
    agent: str
    calls: list[ToolCall] = Field(default_factory=list)
    faults: list[FaultEvent] = Field(default_factory=list)
    outcome: Outcome
    usage: Usage = Field(default_factory=Usage)
    wall_time_s: float = 0.0


# --- Trace records (JSONL, one object per line) ---------------------------


class _Record(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    run_id: str


class RunStart(_Record):
    type: Literal["run_start"] = "run_start"
    scenario: str
    fault_class: str
    seed: int
    agent: str
    policy: PolicyConfig


class ToolCallRecord(_Record, ToolCall):
    type: Literal["tool_call"] = "tool_call"


class FaultRecord(_Record, FaultEvent):
    type: Literal["fault"] = "fault"


class OutcomeRecord(_Record, Outcome):
    type: Literal["outcome"] = "outcome"
    usage: Usage = Field(default_factory=Usage)
    wall_time_s: float = 0.0


TraceRecord = Annotated[
    RunStart | ToolCallRecord | FaultRecord | OutcomeRecord, Field(discriminator="type")
]
