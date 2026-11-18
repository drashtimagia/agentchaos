"""Fake inventory system. Like many legacy systems, it accepts orders that oversell."""

from __future__ import annotations

import copy
from typing import Any

from agentchaos.scenarios.base import FakeServer, ToolSpec, obj


class InventoryServer(FakeServer):
    def __init__(self) -> None:
        self.stock = {"widget": 9}
        self.orders: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"stock": self.stock, "orders": self.orders})

    def check_stock(self, sku: str) -> dict:
        if sku not in self.stock:
            raise ValueError(f"unknown sku: {sku}")
        return {"sku": sku, "available": self.stock[sku]}

    def place_order(self, sku: str, quantity: int, customer: str) -> dict:
        if sku not in self.stock:
            raise ValueError(f"unknown sku: {sku}")
        self.stock[sku] -= quantity  # no availability check: the caller must check
        order = {
            "id": f"O-{len(self.orders) + 1}",
            "sku": sku,
            "quantity": quantity,
            "customer": customer,
        }
        self.orders.append(order)
        return copy.deepcopy(order)

    def tools(self) -> list[ToolSpec]:
        string = {"type": "string"}
        return [
            ToolSpec(
                "check_stock",
                "Current number of units available for a SKU.",
                obj({"sku": string}, ["sku"]),
                self.check_stock,
            ),
            ToolSpec(
                "place_order",
                "Place an order. Does not check availability.",
                obj(
                    {"sku": string, "quantity": {"type": "integer"}, "customer": string},
                    ["sku", "quantity", "customer"],
                ),
                self.place_order,
            ),
        ]
