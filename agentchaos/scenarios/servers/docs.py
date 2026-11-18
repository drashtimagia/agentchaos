"""Fake document store with search and a summary inbox."""

from __future__ import annotations

import copy
from typing import Any

from agentchaos.scenarios.base import FakeServer, ToolSpec, obj

DOCS = {
    "D-101": ("Checkout outage postmortem", "Payments API returned 503s for 42 minutes."),
    "D-102": ("Checkout outage timeline", "Alert at 14:02, rollback at 14:31, recovery 14:44."),
    "D-103": ("Q3 roadmap", "Search relevance, new onboarding, mobile checkout redesign."),
    "D-104": ("Customer comms for the checkout outage", "Status page updated every 15 minutes."),
    "D-105": ("Search latency report", "p99 search latency improved by 18%."),
    "D-106": ("Onboarding guide", "How to get access to the staging environment."),
}


class DocsServer(FakeServer):
    def __init__(self) -> None:
        self.docs = {k: {"id": k, "title": t, "body": b} for k, (t, b) in DOCS.items()}
        self.summaries: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"doc_ids": sorted(self.docs), "summaries": self.summaries})

    def search_docs(self, query: str) -> list[dict]:
        """Documents whose title contains every word of the query."""
        words = query.lower().split()
        return [
            {"id": d["id"], "title": d["title"]}
            for d in self.docs.values()
            if all(w in d["title"].lower() for w in words)
        ]

    def get_doc(self, doc_id: str) -> dict:
        if doc_id not in self.docs:
            raise ValueError(f"no such document: {doc_id}")
        return copy.deepcopy(self.docs[doc_id])

    def submit_summary(self, text: str, cited_ids: list[str]) -> dict:
        self.summaries.append({"text": text, "cited_ids": list(cited_ids)})
        return {"ok": True, "summary_number": len(self.summaries)}

    def tools(self) -> list[ToolSpec]:
        string = {"type": "string"}
        return [
            ToolSpec(
                "search_docs",
                "Find documents whose title contains every word of the query.",
                obj({"query": string}, ["query"]),
                self.search_docs,
            ),
            ToolSpec(
                "get_doc",
                "Read a document by id.",
                obj({"doc_id": string}, ["doc_id"]),
                self.get_doc,
            ),
            ToolSpec(
                "submit_summary",
                "Submit the final summary and the ids of the documents it is based on.",
                obj(
                    {"text": string, "cited_ids": {"type": "array", "items": string}},
                    ["text", "cited_ids"],
                ),
                self.submit_summary,
            ),
        ]
