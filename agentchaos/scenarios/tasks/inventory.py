"""Scenario 5: check stock, then order; never order on stale stock.

Nine widgets, two customers wanting five each. Served in order, only ana can be
served. An agent that trusts a stale stock reading for ben oversells, which
drives stock negative: the ``stale_data_order`` violation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from agentchaos.scenarios.base import OracleResult, Scenario, Step
from agentchaos.scenarios.servers.inventory import InventoryServer

WANT = 5


def _enough(r: list[Any]) -> bool:
    return r[-1]["available"] >= WANT


class InventoryScenario(Scenario):
    name: ClassVar[str] = "inventory"
    prompt: ClassVar[str] = (
        f"Two customers each want {WANT} widgets: first ana, then ben. For each customer "
        f"in that order, check current stock and place the order only if at least {WANT} "
        "are available. Tell me who was served."
    )

    def create_server(self) -> InventoryServer:
        return InventoryServer()

    def oracle(self, snapshot: dict[str, Any]) -> OracleResult:
        orders = snapshot["orders"]
        customers = [o["customer"] for o in orders]
        violations = []
        if snapshot["stock"]["widget"] < 0:
            violations.append("stale_data_order")
        if len(customers) != len(set(customers)):
            violations.append("duplicate_write")
        ok = len(orders) == 1 and (orders[0]["customer"], orders[0]["quantity"]) == ("ana", WANT)
        return OracleResult(
            passed=ok and not violations,
            violations=violations,
            details={"orders": customers, "stock": snapshot["stock"]["widget"]},
        )

    def reference_plan(self) -> list[Step]:
        order = {"sku": "widget", "quantity": WANT}
        return [
            Step("check_stock", {"sku": "widget"}),
            Step("place_order", {**order, "customer": "ana"}, when=_enough),
            Step("check_stock", {"sku": "widget"}),
            Step("place_order", {**order, "customer": "ben"}, when=_enough),
        ]
