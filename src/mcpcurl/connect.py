"""Turn a target string into a live, initialised MCP session.

A target is either a URL (``http://``/``https://``) or a shell command that
starts a stdio server, for example ``python server.py`` or
``npx -y @modelcontextprotocol/server-filesystem /tmp``.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import InitializeResult

try:  # mcp >= 1.28 renamed the transport and takes an httpx client instead of kwargs
    from mcp.client.streamable_http import streamable_http_client as _streamable_http

    _STREAMABLE_TAKES_CLIENT = True
except ImportError:  # pragma: no cover - exercised on older SDKs in CI
    from mcp.client.streamable_http import streamablehttp_client as _streamable_http

    _STREAMABLE_TAKES_CLIENT = False

Transport = Literal["auto", "stdio", "http", "sse"]


@dataclass(slots=True)
class Target:
    """Parsed connection target."""

    raw: str
    transport: Transport = "auto"
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    @property
    def is_url(self) -> bool:
        return self.raw.startswith(("http://", "https://"))

    def resolved_transport(self) -> Literal["stdio", "http", "sse"]:
        if self.transport != "auto":
            return self.transport
        if not self.is_url:
            return "stdio"
        return "sse" if self.raw.rstrip("/").endswith("/sse") else "http"

    def describe(self) -> str:
        return f"{self.resolved_transport()} {self.raw}"


@dataclass(slots=True)
class Connection:
    """An initialised session plus the handshake result the SDK does not keep."""

    session: ClientSession
    init: InitializeResult


def split_command(raw: str) -> list[str]:
    """Split a command line the way a POSIX shell would, on every platform.

    ``shlex`` in non-POSIX mode keeps the quotes around ``"C:\path with spaces"``,
    so on Windows backslashes are escaped first and the POSIX splitter is used.
    """
    if os.name == "nt":
        raw = raw.replace("\\", "\\\\")
    return shlex.split(raw, posix=True)


def parse_kv(pairs: list[str], *, what: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` strings, raising a clear error on malformed input."""
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"{what} must look like KEY=VALUE, got {pair!r}")
        out[key] = value
    return out


@asynccontextmanager
async def connect(target: Target, *, timeout: float = 30.0) -> AsyncIterator[Connection]:
    """Open a session to ``target``, run ``initialize`` and yield the connection."""
    transport = target.resolved_transport()
    if transport == "stdio":
        argv = split_command(target.raw)
        if not argv:
            raise ValueError("empty command")
        params = StdioServerParameters(
            command=argv[0],
            args=argv[1:],
            env={**os.environ, **target.env} if target.env else None,
            cwd=target.cwd,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            yield Connection(session, await session.initialize())
    elif transport == "http":
        async with (
            _open_streamable_http(target, timeout) as (read, write),
            ClientSession(read, write) as session,
        ):
            yield Connection(session, await session.initialize())
    else:
        async with (
            sse_client(target.raw, headers=target.headers or None, timeout=timeout) as (
                read,
                write,
            ),
            ClientSession(read, write) as session,
        ):
            yield Connection(session, await session.initialize())


@asynccontextmanager
async def _open_streamable_http(target: Target, timeout: float) -> AsyncIterator[tuple[Any, Any]]:
    """Open a Streamable HTTP transport on either SDK generation."""
    if _STREAMABLE_TAKES_CLIENT:
        import httpx

        async with (
            httpx.AsyncClient(
                headers=target.headers or None,
                timeout=httpx.Timeout(timeout, read=300),
                follow_redirects=True,
            ) as client,
            _streamable_http(target.raw, http_client=client) as (read, write, _),
        ):
            yield read, write
    else:
        async with _streamable_http(
            target.raw, headers=target.headers or None, timeout=timeout
        ) as (read, write, _):
            yield read, write
