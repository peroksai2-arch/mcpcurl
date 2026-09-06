"""Collect everything a server exposes into one plain data structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.types import Prompt, Resource, ResourceTemplate, Tool

from .connect import Connection


@dataclass(slots=True)
class Inventory:
    """Snapshot of a server's advertised surface."""

    server_name: str
    server_version: str
    protocol_version: str
    instructions: str | None
    capabilities: dict[str, Any]
    tools: list[Tool] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    resource_templates: list[ResourceTemplate] = field(default_factory=list)
    prompts: list[Prompt] = field(default_factory=list)

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": {
                "name": self.server_name,
                "version": self.server_version,
                "protocol_version": self.protocol_version,
                "instructions": self.instructions,
                "capabilities": self.capabilities,
            },
            "tools": [
                t.model_dump(mode="json", exclude_none=True, by_alias=True) for t in self.tools
            ],
            "resources": [
                r.model_dump(mode="json", exclude_none=True, by_alias=True) for r in self.resources
            ],
            "resource_templates": [
                r.model_dump(mode="json", exclude_none=True, by_alias=True)
                for r in self.resource_templates
            ],
            "prompts": [
                p.model_dump(mode="json", exclude_none=True, by_alias=True) for p in self.prompts
            ],
        }


async def gather(conn: Connection) -> Inventory:
    """Query the session for tools, resources and prompts.

    Servers only have to implement the capabilities they advertise, so each
    listing is skipped when the capability is absent rather than erroring.
    """
    init = conn.init
    session = conn.session
    caps = init.capabilities

    inv = Inventory(
        server_name=init.serverInfo.name,
        server_version=init.serverInfo.version,
        protocol_version=str(init.protocolVersion),
        instructions=init.instructions,
        capabilities=caps.model_dump(exclude_none=True),
    )

    if caps.tools is not None:
        inv.tools = await _paginate(session.list_tools, "tools")
    if caps.resources is not None:
        inv.resources = await _paginate(session.list_resources, "resources")
        try:
            inv.resource_templates = await _paginate(
                session.list_resource_templates, "resourceTemplates"
            )
        except Exception:  # noqa: BLE001 - optional in older servers
            inv.resource_templates = []
    if caps.prompts is not None:
        inv.prompts = await _paginate(session.list_prompts, "prompts")
    return inv


async def _paginate(method: Any, attr: str) -> list[Any]:
    items: list[Any] = []
    cursor: str | None = None
    while True:
        result = await method(cursor) if cursor else await method()
        items.extend(getattr(result, attr))
        cursor = result.nextCursor
        if not cursor:
            return items
