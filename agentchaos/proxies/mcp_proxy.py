"""Transparent MCP proxy with fault injection.

The proxy mirrors the upstream server's tool list and forwards every tool call
through an ``Injector``. With no fault firing, the upstream's response objects
are returned unchanged. Injected errors become MCP tool errors (``isError``),
which is how real servers report failures to agents.

One proxy is one run: it has one seed, one call counter and one trace. Run
several proxies side by side for parallel runs.
"""

from __future__ import annotations

import shlex
from typing import Any

import mcp_types as types
import uvicorn
from mcp import Client, StdioServerParameters
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from agentchaos.core.faults import ToolFault
from agentchaos.core.models import PolicyConfig
from agentchaos.core.policy import Injector, Sink
from agentchaos.scenarios.mcp_server import error_result


class ChaosProxy:
    def __init__(
        self,
        upstream: Client,
        policy: PolicyConfig,
        *,
        seed: int | None = None,
        sink: Sink | None = None,
        name: str = "agentchaos-proxy",
    ):
        self.upstream = upstream
        self.injector = Injector(policy, seed=seed, sink=sink)
        self.server = Server(name, on_list_tools=self._list_tools, on_call_tool=self._call_tool)

    async def _list_tools(self, ctx: Any, params: Any) -> types.ListToolsResult:
        return await self.upstream.list_tools(cursor=params.cursor if params else None)

    async def _call_tool(
        self, ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        async def forward(**args: Any) -> types.CallToolResult:
            return await self.upstream.call_tool(params.name, args)

        try:
            return await self.injector.call(params.name, params.arguments or {}, forward)
        except ToolFault as e:
            return error_result(str(e))


def upstream_client(target: str) -> Client:
    """A client for ``target``: an http(s) URL, or a shell-style command to run over stdio."""
    if target.startswith(("http://", "https://")):
        return Client(target)
    argv = shlex.split(target)
    return Client(StdioServerParameters(command=argv[0], args=argv[1:]))


async def serve_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def serve_http(server: Server, host: str = "127.0.0.1", port: int = 8765) -> None:
    app = server.streamable_http_app(host=host)
    await uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning")).serve()
