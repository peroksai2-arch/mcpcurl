"""Human-readable and Markdown output for inventories and tool results."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, Tool
from rich.console import Console
from rich.table import Table

from .inventory import Inventory


def schema_summary(schema: dict[str, Any] | None) -> str:
    """One-line signature like ``a: integer, b: integer, verbose?: boolean``."""
    if not schema:
        return ""
    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parts = []
    for name, spec in props.items():
        typ = spec.get("type") if isinstance(spec, dict) else None
        if isinstance(typ, list):
            typ = "|".join(str(t) for t in typ)
        if typ is None and isinstance(spec, dict) and "anyOf" in spec:
            typ = "|".join(str(o.get("type", "?")) for o in spec["anyOf"] if isinstance(o, dict))
        suffix = "" if name in required else "?"
        parts.append(f"{name}{suffix}: {typ or 'any'}")
    return ", ".join(parts)


def print_inventory(inv: Inventory, console: Console, *, verbose: bool = False) -> None:
    console.print(
        f"[bold]{inv.server_name}[/] v{inv.server_version}  [dim]protocol {inv.protocol_version}[/]"
    )
    if inv.instructions:
        console.print(f"[dim]{inv.instructions.strip()}[/]")
    console.print()

    if inv.tools:
        table = Table(title=f"Tools ({len(inv.tools)})", show_lines=verbose, expand=True)
        table.add_column("name", style="cyan", no_wrap=True)
        table.add_column("arguments")
        table.add_column("description")
        for t in inv.tools:
            desc = (t.description or "").strip()
            if not verbose:
                desc = desc.splitlines()[0] if desc else ""
            table.add_row(t.name, schema_summary(t.inputSchema), desc)
        console.print(table)
    else:
        console.print("[yellow]no tools[/]")

    if inv.resources or inv.resource_templates:
        table = Table(
            title=f"Resources ({len(inv.resources) + len(inv.resource_templates)})", expand=True
        )
        table.add_column("uri", style="cyan")
        table.add_column("name")
        table.add_column("mime")
        for r in inv.resources:
            table.add_row(str(r.uri), r.name or "", r.mimeType or "")
        for r in inv.resource_templates:
            table.add_row(r.uriTemplate, r.name or "", r.mimeType or "")
        console.print(table)

    if inv.prompts:
        table = Table(title=f"Prompts ({len(inv.prompts)})", expand=True)
        table.add_column("name", style="cyan")
        table.add_column("arguments")
        table.add_column("description")
        for p in inv.prompts:
            args = ", ".join(f"{a.name}{'' if a.required else '?'}" for a in (p.arguments or []))
            table.add_row(p.name, args, (p.description or "").strip())
        console.print(table)


def result_to_plain(result: CallToolResult) -> dict[str, Any]:
    """Flatten a CallToolResult into JSON-friendly data."""
    content: list[Any] = []
    for block in result.content:
        if block.type == "text":
            text = block.text
            try:
                content.append(json.loads(text))
            except (ValueError, TypeError):
                content.append(text)
        else:
            content.append(block.model_dump(mode="json", exclude_none=True, by_alias=True))
    out: dict[str, Any] = {"is_error": bool(result.isError), "content": content}
    if result.structuredContent is not None:
        out["structured"] = result.structuredContent
    return out


def result_text(result: CallToolResult) -> str:
    """All text blocks joined, used for substring assertions."""
    return "\n".join(b.text for b in result.content if b.type == "text")


def to_markdown(inv: Inventory) -> str:
    lines = [f"# {inv.server_name}", ""]
    lines.append(f"Version `{inv.server_version}`, MCP protocol `{inv.protocol_version}`.")
    if inv.instructions:
        lines += ["", inv.instructions.strip()]
    if inv.tools:
        lines += ["", "## Tools", ""]
        for t in inv.tools:
            lines += _tool_markdown(t)
    if inv.resources or inv.resource_templates:
        lines += [
            "",
            "## Resources",
            "",
            "| URI | Name | MIME | Description |",
            "|---|---|---|---|",
        ]
        for r in inv.resources:
            lines.append(
                f"| `{r.uri}` | {r.name or ''} | {r.mimeType or ''} | "
                f"{(r.description or '').strip()} |"
            )
        for r in inv.resource_templates:
            lines.append(
                f"| `{r.uriTemplate}` | {r.name or ''} | {r.mimeType or ''} | "
                f"{(r.description or '').strip()} |"
            )
    if inv.prompts:
        lines += ["", "## Prompts", ""]
        for p in inv.prompts:
            lines.append(f"### `{p.name}`")
            if p.description:
                lines += ["", p.description.strip()]
            if p.arguments:
                lines += ["", "| Argument | Required | Description |", "|---|---|---|"]
                for a in p.arguments:
                    lines.append(
                        f"| `{a.name}` | {'yes' if a.required else 'no'} | "
                        f"{(a.description or '').strip()} |"
                    )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _tool_markdown(t: Tool) -> list[str]:
    lines = [f"### `{t.name}`"]
    if t.description:
        lines += ["", t.description.strip()]
    schema = t.inputSchema or {}
    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if props:
        lines += ["", "| Argument | Type | Required | Description |", "|---|---|---|---|"]
        for name, spec in props.items():
            spec = spec if isinstance(spec, dict) else {}
            typ = spec.get("type", "any")
            if isinstance(typ, list):
                typ = " or ".join(typ)
            desc = (spec.get("description") or "").strip().replace("\n", " ")
            lines.append(f"| `{name}` | {typ} | {'yes' if name in required else 'no'} | {desc} |")
    else:
        lines += ["", "_No arguments._"]
    lines.append("")
    return lines
