"""Disk-backed trial-level response cache.

Cache key: SHA-256(agent_name + "\\n" + scenario_name + "\\n" + fault_class
           + "\\n" + str(seed) + "\\n" + policy_json)

Storing a full ``AgentResult`` per cache slot means LLM agents don't need to
call the API on reruns of the same (agent, scenario, fault class, seed)
combination.  The ``--max-cost`` guard accumulates ``usage.cost_usd`` across
all runs in an experiment and raises ``CostLimitExceeded`` once the budget is
exhausted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from agentchaos.core.models import PolicyConfig, Usage
from agentchaos.runners.base import AgentResult

_DEFAULT_DIR = Path.home() / ".cache" / "agentchaos"


class CostLimitExceeded(Exception):
    pass


@dataclass
class ResponseCache:
    directory: Path = _DEFAULT_DIR
    max_cost_usd: float | None = None
    _spent: float = 0.0

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _key(
        self,
        agent_name: str,
        scenario_name: str,
        fault_class: str,
        seed: int,
        policy: PolicyConfig,
    ) -> str:
        blob = "\n".join(
            [
                agent_name,
                scenario_name,
                fault_class,
                str(seed),
                policy.model_dump_json(),
            ]
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(
        self,
        agent_name: str,
        scenario_name: str,
        fault_class: str,
        seed: int,
        policy: PolicyConfig,
    ) -> AgentResult | None:
        p = self._path(self._key(agent_name, scenario_name, fault_class, seed, policy))
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return AgentResult(
            final_message=data["final_message"],
            usage=Usage(**data.get("usage", {})),
        )

    def put(
        self,
        agent_name: str,
        scenario_name: str,
        fault_class: str,
        seed: int,
        policy: PolicyConfig,
        result: AgentResult,
    ) -> None:
        p = self._path(self._key(agent_name, scenario_name, fault_class, seed, policy))
        p.write_text(
            json.dumps(
                {
                    "final_message": result.final_message,
                    "usage": {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "cost_usd": result.usage.cost_usd,
                    },
                }
            )
        )

    def charge(self, cost_usd: float) -> None:
        """Accumulate cost and raise if the budget is exhausted."""
        self._spent += cost_usd
        if self.max_cost_usd is not None and self._spent > self.max_cost_usd:
            raise CostLimitExceeded(
                f"cost limit ${self.max_cost_usd:.4f} exceeded (spent ${self._spent:.4f})"
            )

    @property
    def spent(self) -> float:
        return self._spent
