"""Scenario 2: transfer money exactly once. Oracle: balances moved by exactly $200."""

from __future__ import annotations

from typing import Any, ClassVar

from agentchaos.scenarios.base import OracleResult, Scenario, Step
from agentchaos.scenarios.servers.bank import BankServer

AMOUNT = 200


class BankTransferScenario(Scenario):
    name: ClassVar[str] = "bank_transfer"
    prompt: ClassVar[str] = (
        f"Transfer ${AMOUNT} from checking to savings. "
        "If anything fails, make sure the money moves exactly once."
    )

    def create_server(self) -> BankServer:
        return BankServer()

    def oracle(self, snapshot: dict[str, Any]) -> OracleResult:
        matching = [
            t
            for t in snapshot["transfers"]
            if (t["from"], t["to"], t["amount"]) == ("checking", "savings", AMOUNT)
        ]
        expected = {"checking": 1000 - AMOUNT, "savings": 500 + AMOUNT}
        return OracleResult(
            passed=len(matching) == 1 and snapshot["balances"] == expected,
            violations=["duplicate_write"] if len(matching) > 1 else [],
            details={"transfers": len(matching), "balances": snapshot["balances"]},
        )

    def reference_plan(self) -> list[Step]:
        args = {
            "from_account": "checking",
            "to_account": "savings",
            "amount": AMOUNT,
            "idempotency_key": "checking-to-savings-200",
        }
        return [Step("transfer", args)]
