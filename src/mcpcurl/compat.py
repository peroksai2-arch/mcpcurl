"""Smooth over the differences between mcp 1.x and 2.x.

The 2.x SDK renamed model attributes from camelCase (``serverInfo``,
``inputSchema``) to snake_case and changed a few call signatures. Everything
here is a tiny shim so the rest of the code can be written once.
"""

from __future__ import annotations

import re
from typing import Any

from mcp.types import InitializeResult, PaginatedRequestParams

MCP2 = "server_info" in InitializeResult.model_fields


def attr(obj: Any, snake: str, default: Any = None) -> Any:
    """Read ``obj.snake`` (2.x) or its camelCase twin (1.x)."""
    if hasattr(obj, snake):
        return getattr(obj, snake)
    camel = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), snake)
    return getattr(obj, camel, default)


def page_params(cursor: str | None) -> dict[str, Any]:
    """Keyword arguments for a paginated ``list_*`` call."""
    if cursor is None:
        return {}
    return {"params": PaginatedRequestParams(cursor=cursor)}


def resource_uri(uri: str) -> Any:
    """``read_resource`` wants ``str`` on 2.x and ``AnyUrl`` on 1.x."""
    if MCP2:
        return uri
    from pydantic import AnyUrl

    return AnyUrl(uri)
