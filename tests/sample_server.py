"""Tiny FastMCP server used by the test-suite and the README examples.

Run it directly to talk to it over stdio::

    mcpcurl list "python tests/sample_server.py"
"""

from __future__ import annotations

import asyncio

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sample", instructions="A toy server with one of everything.")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def echo(text: str, upper: bool = False) -> str:
    """Return the text, optionally upper-cased."""
    return text.upper() if upper else text


@mcp.tool()
def fail(message: str = "boom") -> str:
    """Always raises, to exercise error reporting."""
    raise RuntimeError(message)


@mcp.tool()
async def slow(seconds: float = 0.2) -> str:
    """Sleep for a while, to exercise latency budgets."""
    await asyncio.sleep(seconds)
    return f"slept {seconds}"


@mcp.tool()
def undocumented(x: int) -> int:
    return x * 2


@mcp.resource("info://about")
def about() -> str:
    """Static description of this server."""
    return "sample server for mcpcurl"


@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


@mcp.prompt()
def summarize(topic: str) -> str:
    """Ask for a short summary of a topic."""
    return f"Summarise {topic} in three sentences."


if __name__ == "__main__":
    mcp.run(transport="stdio")
