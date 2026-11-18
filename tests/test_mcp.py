import asyncio
import json
import socket
import sys

import pytest
import uvicorn
from mcp import Client, StdioServerParameters

from agentchaos.core.models import FaultRule, PolicyConfig
from agentchaos.core.policy import load_policy
from agentchaos.core.recorder import Recorder, read_trace
from agentchaos.proxies.mcp_proxy import ChaosProxy
from agentchaos.scenarios.mcp_server import mcp_server
from agentchaos.scenarios.servers.ticketing import TicketingServer

CALLS = [
    ("create_ticket", {"title": "Broken login", "priority": "high"}),
    ("assign_ticket", {"ticket_id": "T-1", "assignee": "bob"}),
    ("search_tickets", {"query": "login"}),
    ("assign_ticket", {"ticket_id": "T-1", "assignee": "nobody"}),  # upstream tool error
    ("list_users", {}),
]


def upstream():
    return mcp_server(TicketingServer(), "ticketing")


async def exercise(client):
    tools = await client.list_tools()
    results = [await client.call_tool(name, args) for name, args in CALLS]
    return tools.model_dump(), [r.model_dump() for r in results]


async def test_proxy_is_transparent_with_no_faults():
    async with Client(upstream()) as direct:
        expected = await exercise(direct)
    async with Client(upstream()) as up:
        proxy = ChaosProxy(up, PolicyConfig())
        async with Client(proxy.server) as client:
            assert await exercise(client) == expected
    assert [c.ok for c in proxy.injector.calls] == [True, True, True, False, True]


async def proxied_call(policy, name="create_ticket", args=None, sink=None):
    async with Client(upstream()) as up:
        proxy = ChaosProxy(up, policy, seed=3, sink=sink)
        async with Client(proxy.server) as client:
            result = await client.call_tool(name, args or {"title": "x"})
            return result, proxy


async def test_injected_error_becomes_mcp_tool_error():
    result, proxy = await proxied_call(PolicyConfig(rules=[FaultRule(fault="rate_limit")]))
    assert result.is_error
    assert "429" in result.content[0].text
    assert proxy.injector.events[0].fault == "rate_limit"


async def test_malformed_json_over_mcp():
    result, _ = await proxied_call(PolicyConfig(rules=[FaultRule(fault="malformed_json")]))
    assert not result.is_error
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.content[0].text)


async def test_schema_drift_over_mcp():
    rules = [FaultRule(fault="schema_drift", params={"field": "id"})]
    result, _ = await proxied_call(PolicyConfig(rules=rules))
    assert set(json.loads(result.content[0].text)) == {
        "id_v2",
        "title",
        "description",
        "priority",
        "assignee",
    }


async def test_timeout_after_reaches_upstream_over_mcp():
    rules = [FaultRule(fault="timeout", params={"phase": "after"})]
    async with Client(upstream()) as up:
        proxy = ChaosProxy(up, PolicyConfig(rules=rules))
        async with Client(proxy.server) as client:
            result = await client.call_tool("create_ticket", {"title": "x"})
        tickets = await up.call_tool("search_tickets", {"query": "x"})
    assert result.is_error and "timed out" in result.content[0].text
    assert len(json.loads(tickets.content[0].text)) == 1  # the write happened anyway


async def test_proxy_writes_trace(tmp_path):
    path = tmp_path / "t.jsonl"
    with Recorder(path) as rec:
        await proxied_call(PolicyConfig(rules=[FaultRule(fault="timeout")]), sink=rec.sink("r1"))
    assert [r.type for r in read_trace(path)] == ["tool_call", "fault"]


async def test_stdio_end_to_end_through_cli(tmp_path):
    """Agent -> proxy subprocess -> fake server subprocess, all over stdio."""
    trace = tmp_path / "proxy.jsonl"
    serve = f"{sys.executable} -m agentchaos.cli serve ticketing"
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "agentchaos.cli",
            "proxy",
            "--upstream",
            serve,
            "--profile",
            "rate-limited",
            "--seed",
            "1",
            "--trace",
            str(trace),
        ],
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        results = [await client.call_tool("list_users", {}) for _ in range(20)]
    assert names == {"list_users", "create_ticket", "assign_ticket", "search_tickets"}
    limited = [r for r in results if r.is_error]
    assert 0 < len(limited) < 20 and "429" in limited[0].content[0].text
    records = list(read_trace(trace))
    assert records[0].type == "run_start" and records[0].seed == 1
    assert sum(r.type == "fault" for r in records) == len(limited)


async def test_streamable_http_proxy():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    async with Client(upstream()) as up:
        proxy = ChaosProxy(
            up, load_policy({"rules": [{"fault": "rate_limit", "call_indices": [1]}]})
        )
        app = proxy.server.streamable_http_app()
        server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
        try:
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                first = await client.call_tool("list_users", {})
                second = await client.call_tool("list_users", {})
        finally:
            server.should_exit = True
            await task
    assert json.loads(first.content[0].text) == ["alice", "bob", "carol"]
    assert second.is_error and "429" in second.content[0].text
