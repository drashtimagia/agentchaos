"""Fake bank with idempotent transfers."""

from __future__ import annotations

import copy
from typing import Any

from agentchaos.scenarios.base import FakeServer, ToolSpec, obj


class BankServer(FakeServer):
    def __init__(self) -> None:
        self.balances = {"checking": 1000, "savings": 500}
        self.transfers: list[dict[str, Any]] = []
        self._by_key: dict[str, dict[str, Any]] = {}

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"balances": self.balances, "transfers": self.transfers})

    def get_balance(self, account: str) -> dict:
        self._check(account)
        return {"account": account, "balance": self.balances[account]}

    def transfer(
        self, from_account: str, to_account: str, amount: int, idempotency_key: str = ""
    ) -> dict:
        """Move money. Repeating a call with the same idempotency key is a no-op."""
        if idempotency_key in self._by_key:
            return copy.deepcopy(self._by_key[idempotency_key])
        self._check(from_account)
        self._check(to_account)
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self.balances[from_account] < amount:
            raise ValueError("insufficient funds")
        self.balances[from_account] -= amount
        self.balances[to_account] += amount
        record = {
            "id": f"TX-{len(self.transfers) + 1}",
            "from": from_account,
            "to": to_account,
            "amount": amount,
        }
        self.transfers.append(record)
        if idempotency_key:
            self._by_key[idempotency_key] = record
        return copy.deepcopy(record)

    def list_transfers(self) -> list[dict]:
        return copy.deepcopy(self.transfers)

    def _check(self, account: str) -> None:
        if account not in self.balances:
            raise ValueError(f"no such account: {account}")

    def tools(self) -> list[ToolSpec]:
        string, integer = {"type": "string"}, {"type": "integer"}
        return [
            ToolSpec(
                "get_balance",
                "Get an account's balance in dollars.",
                obj({"account": string}, ["account"]),
                self.get_balance,
            ),
            ToolSpec(
                "transfer",
                "Move dollars between accounts. Calls repeated with the same "
                "idempotency_key are applied at most once.",
                obj(
                    {
                        "from_account": string,
                        "to_account": string,
                        "amount": integer,
                        "idempotency_key": string,
                    },
                    ["from_account", "to_account", "amount"],
                ),
                self.transfer,
            ),
            ToolSpec("list_transfers", "List completed transfers.", obj({}), self.list_transfers),
        ]
