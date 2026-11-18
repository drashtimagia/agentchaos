"""Expose a fake tool server over MCP."""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server

from agentchaos.scenarios.base import FakeServer


def error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=True
    )


def mcp_server(fake: FakeServer, name: str) -> Server:
    """An MCP server whose tools are ``fake``'s tools. Results are JSON text."""
    specs = {spec.name: spec for spec in fake.tools()}

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=s.name, description=s.description, input_schema=s.parameters)
                for s in specs.values()
            ]
        )

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        spec = specs.get(params.name)
        if spec is None:
            return error_result(f"Unknown tool: {params.name}")
        try:
            result = await spec.call(params.arguments or {})
        except Exception as e:
            return error_result(str(e))
        text = json.dumps(result)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    return Server(name, on_list_tools=list_tools, on_call_tool=call_tool)
