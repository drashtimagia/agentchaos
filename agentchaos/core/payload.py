"""Read and rewrite tool results, whether they are plain Python values or MCP results.

Faults that corrupt responses (malformed JSON, schema drift) go through these
helpers so they work the same in-process and behind the MCP proxy. Results that
no fault touches are passed through as the original object, which is what makes
the proxy byte-for-byte transparent when nothing fires.
"""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types


class RawText(str):
    """A response body that is not (or no longer) valid JSON."""


def get_data(result: Any) -> Any:
    """The JSON value inside a result. Raises ``ValueError`` if there isn't one."""
    if isinstance(result, types.CallToolResult):
        if result.is_error:
            raise ValueError("error result")
        if result.structured_content is not None:
            return result.structured_content
        texts = [c.text for c in result.content if isinstance(c, types.TextContent)]
        if len(texts) != 1:
            raise ValueError("expected exactly one text block")
        return json.loads(texts[0])
    if isinstance(result, RawText):
        return json.loads(result)
    return result


def with_data(result: Any, data: Any) -> Any:
    """``result`` with its JSON value replaced by ``data``."""
    if isinstance(result, types.CallToolResult):
        structured = data if result.structured_content is not None else None
        return result.model_copy(
            update={"content": [_text(json.dumps(data))], "structured_content": structured}
        )
    return data


def with_text(result: Any, text: str) -> Any:
    """``result`` with its body replaced by raw (possibly invalid) text."""
    if isinstance(result, types.CallToolResult):
        return result.model_copy(update={"content": [_text(text)], "structured_content": None})
    return RawText(text)


def is_error(result: Any) -> bool:
    """True for MCP tool-error results (the upstream reported a failure)."""
    return isinstance(result, types.CallToolResult) and bool(result.is_error)


def jsonable(result: Any) -> Any:
    """A JSON-serializable form of ``result`` for the trace."""
    if isinstance(result, types.CallToolResult):
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)
    return result


def _text(text: str) -> types.TextContent:
    return types.TextContent(type="text", text=text)
