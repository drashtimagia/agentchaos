"""Per-fault-class summary statistics.

The overall weighted resilience score is intentionally not defined yet: the
formula needs sign-off (see DESIGN.md, "Open questions").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from agentchaos.core.models import Run
from agentchaos.execution import CLEAN


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval; well-behaved at small n and at 0% / 100%."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class ClassSummary:
    fault_class: str
    n: int
    successes: int
    success_ci: tuple[float, float]
    degradation: float | None  # success rate / clean success rate
    safety_violation_rate: float
    mean_calls: float
    mean_faults: float

    @property
    def success_rate(self) -> float:
        return self.successes / self.n if self.n else 0.0


def summarize(runs: list[Run]) -> list[ClassSummary]:
    groups: dict[str, list[Run]] = {}
    for r in runs:
        groups.setdefault(r.fault_class, []).append(r)

    def rate(rs: list[Run]) -> float:
        return sum(r.outcome.task_success for r in rs) / len(rs)

    clean = rate(groups[CLEAN]) if groups.get(CLEAN) else None
    out = []
    for fc, rs in groups.items():
        n, k = len(rs), sum(r.outcome.task_success for r in rs)
        out.append(
            ClassSummary(
                fault_class=fc,
                n=n,
                successes=k,
                success_ci=wilson(k, n),
                degradation=(k / n) / clean if clean else None,
                safety_violation_rate=sum(bool(r.outcome.safety_violations) for r in rs) / n,
                mean_calls=sum(len(r.calls) for r in rs) / n,
                mean_faults=sum(len(r.faults) for r in rs) / n,
            )
        )
    return out
