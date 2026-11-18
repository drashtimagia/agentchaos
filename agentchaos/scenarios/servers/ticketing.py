"""Fake ticketing system (think a minimal issue tracker) with in-memory state."""

from __future__ import annotations

import copy
from typing import Any

from agentchaos.scenarios.base import FakeServer, ToolSpec

PRIORITIES = ("low", "medium", "high")


class TicketingServer(FakeServer):
    def __init__(self, users: tuple[str, ...] = ("alice", "bob", "carol")):
        self.users = list(users)
        self.tickets: dict[str, dict[str, Any]] = {}
        self._next_id = 1

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"users": self.users, "tickets": self.tickets})

    # --- tools -----------------------------------------------------------

    def list_users(self) -> list[str]:
        return list(self.users)

    def create_ticket(self, title: str, description: str = "", priority: str = "medium") -> dict:
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        ticket_id = f"T-{self._next_id}"
        self._next_id += 1
        ticket = {
            "id": ticket_id,
            "title": title,
            "description": description,
            "priority": priority,
            "assignee": None,
        }
        self.tickets[ticket_id] = ticket
        return copy.deepcopy(ticket)

    def assign_ticket(self, ticket_id: str, assignee: str) -> dict:
        if ticket_id not in self.tickets:
            raise ValueError(f"no such ticket: {ticket_id}")
        if assignee not in self.users:
            raise ValueError(f"no such user: {assignee}")
        self.tickets[ticket_id]["assignee"] = assignee
        return copy.deepcopy(self.tickets[ticket_id])

    def search_tickets(self, query: str = "") -> list[dict]:
        q = query.lower()
        return [copy.deepcopy(t) for t in self.tickets.values() if q in t["title"].lower()]

    def tools(self) -> list[ToolSpec]:
        string = {"type": "string"}
        priority = {"type": "string", "enum": list(PRIORITIES)}
        return [
            ToolSpec(
                "list_users",
                "List usernames that tickets can be assigned to.",
                _obj({}),
                self.list_users,
            ),
            ToolSpec(
                "create_ticket",
                "Create a new ticket. Returns the ticket with its id.",
                _obj({"title": string, "description": string, "priority": priority}, ["title"]),
                self.create_ticket,
            ),
            ToolSpec(
                "assign_ticket",
                "Assign an existing ticket to a user.",
                _obj({"ticket_id": string, "assignee": string}, ["ticket_id", "assignee"]),
                self.assign_ticket,
            ),
            ToolSpec(
                "search_tickets",
                "Search tickets whose title contains the query.",
                _obj({"query": string}),
                self.search_tickets,
            ),
        ]


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}
