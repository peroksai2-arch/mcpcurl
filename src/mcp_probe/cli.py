"""Command line entry point: ``mcp-probe list|call|read|prompt|test|docs``."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import AnyUrl
from rich.console import Console
from rich.table import Table

from .connect import Target, connect, parse_kv
from .inventory import gather
from .render import print_inventory, result_to_plain, to_markdown
from .suite import Suite, coerce_args, parse_cli_value, run_suite

app = typer.Typer(
    help="Inspect, call, smoke-test and document any MCP server.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

TargetArg = Annotated[
    str,
    typer.Argument(
        help='URL or command, e.g. "python server.py" or http://localhost:8000/mcp',
        show_default=False,
    ),
]
TransportOpt = Annotated[
    str, typer.Option("--transport", "-t", help="auto, stdio, http or sse", show_default=True)
]
HeaderOpt = Annotated[
    list[str] | None, typer.Option("--header", "-H", help="HTTP header KEY=VALUE (repeatable)")
]
EnvOpt = Annotated[
    list[str] | None, typer.Option("--env", "-e", help="Env var KEY=VALUE for stdio servers")
]
CwdOpt = Annotated[str | None, typer.Option("--cwd", help="Working directory for stdio servers")]
TimeoutOpt = Annotated[float, typer.Option("--timeout", help="Connect/request timeout, seconds")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output")]


def _target(
    raw: str,
    transport: str,
    headers: list[str] | None,
    env: list[str] | None,
    cwd: str | None,
) -> Target:
    if transport not in ("auto", "stdio", "http", "sse"):
        raise typer.BadParameter("transport must be auto, stdio, http or sse")
    try:
        return Target(
            raw=raw,
            transport=transport,  # type: ignore[arg-type]
            headers=parse_kv(headers or [], what="--header"),
            env=parse_kv(env or [], what="--env"),
            cwd=cwd,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except (ConnectionError, OSError, TimeoutError) as exc:
        err.print(f"[red]connection failed:[/] {exc}")
        raise typer.Exit(2) from None
    except FileNotFoundError as exc:
        err.print(f"[red]command not found:[/] {exc}")
        raise typer.Exit(2) from None


@app.command("list")
def list_cmd(
    target: TargetArg,
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
    as_json: JsonOpt = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Full descriptions")] = False,
) -> None:
    """List tools, resources and prompts the server advertises."""

    async def go() -> None:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            inv = await gather(c)
        if as_json:
            print(json.dumps(inv.to_dict(), indent=2, default=str))
        else:
            print_inventory(inv, console, verbose=verbose)

    _run(go())


@app.command()
def call(
    target: TargetArg,
    tool: Annotated[str, typer.Argument(help="Tool name", show_default=False)],
    arg: Annotated[
        list[str] | None,
        typer.Option("--arg", "-a", help="Argument KEY=VALUE; VALUE is parsed as JSON if possible"),
    ] = None,
    json_args: Annotated[
        str | None, typer.Option("--json-args", "-j", help="All arguments as one JSON object")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Check args against the tool schema")
    ] = True,
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
    as_json: JsonOpt = False,
) -> None:
    """Call one tool and print the result. Exit code 1 if the server reports an error."""
    args: dict[str, Any] = {}
    if json_args:
        try:
            args.update(json.loads(json_args))
        except ValueError as exc:
            raise typer.BadParameter(f"--json-args is not valid JSON: {exc}") from None
    for pair in arg or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"--arg must look like KEY=VALUE, got {pair!r}")
        args[key] = parse_cli_value(value)

    async def go() -> int:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            if validate:
                inv = await gather(c)
                spec = inv.tool(tool)
                if spec is None:
                    err.print(
                        f"[red]unknown tool[/] {tool!r}. Known: {[t.name for t in inv.tools]}"
                    )
                    return 2
                try:
                    coerce_args(spec.inputSchema, args)
                except ValueError as exc:
                    err.print(f"[red]invalid arguments:[/] {exc}")
                    return 2
            result = await c.session.call_tool(tool, args)
        plain = result_to_plain(result)
        if as_json:
            print(json.dumps(plain, indent=2, default=str))
        else:
            for block in plain["content"]:
                if isinstance(block, str):
                    console.print(block, markup=False, highlight=False)
                else:
                    console.print_json(json.dumps(block, default=str))
            if "structured" in plain and not plain["content"]:
                console.print_json(json.dumps(plain["structured"], default=str))
        return 1 if plain["is_error"] else 0

    raise typer.Exit(_run(go()))


@app.command()
def read(
    target: TargetArg,
    uri: Annotated[str, typer.Argument(help="Resource URI", show_default=False)],
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
) -> None:
    """Read a resource and print its contents."""

    async def go() -> None:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            res = await c.session.read_resource(AnyUrl(uri))
        for content in res.contents:
            text = getattr(content, "text", None)
            if text is not None:
                console.print(text, markup=False, highlight=False)
            else:
                blob = getattr(content, "blob", "")
                console.print(f"[dim]<{content.mimeType or 'binary'} {len(blob)} base64 chars>[/]")

    _run(go())


@app.command()
def prompt(
    target: TargetArg,
    name: Annotated[str, typer.Argument(help="Prompt name", show_default=False)],
    arg: Annotated[list[str] | None, typer.Option("--arg", "-a", help="Argument KEY=VALUE")] = None,
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
) -> None:
    """Render a prompt and print its messages."""
    args = parse_kv(arg or [], what="--arg")

    async def go() -> None:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            res = await c.session.get_prompt(name, args)
        for m in res.messages:
            text = getattr(m.content, "text", "<non-text content>")
            console.print(f"[bold]{m.role}[/]: {text}", markup=False)

    _run(go())


@app.command()
def test(
    target: TargetArg,
    suite: Annotated[
        Path | None, typer.Option("--suite", "-s", help="YAML file with cases", exists=True)
    ] = None,
    smoke: Annotated[bool, typer.Option("--smoke/--no-smoke", help="Run static checks")] = True,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Check args against tool schemas")
    ] = True,
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
    as_json: JsonOpt = False,
) -> None:
    """Run smoke checks plus an optional YAML suite. Exit code 1 on any failure."""
    loaded = Suite.load(suite) if suite else None

    async def go() -> list[Any]:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            return await run_suite(c, loaded, smoke=smoke, validate_args=validate)

    results = _run(go())
    failed = [r for r in results if not r.ok]
    if as_json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        table = Table(expand=True)
        table.add_column("", width=2)
        table.add_column("check", overflow="fold")
        table.add_column("ms", justify="right", width=7)
        table.add_column("detail", overflow="fold")
        for r in results:
            mark = "[green]ok[/]" if r.ok else "[red]FAIL[/]"
            table.add_row(mark, r.name, f"{r.duration_ms:.0f}" if r.duration_ms else "", r.message)
        console.print(table)
        console.print(
            f"[bold]{len(results) - len(failed)} passed, {len(failed)} failed[/]",
            style="green" if not failed else "red",
        )
    raise typer.Exit(1 if failed else 0)


@app.command()
def docs(
    target: TargetArg,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write Markdown here instead of stdout")
    ] = None,
    transport: TransportOpt = "auto",
    header: HeaderOpt = None,
    env: EnvOpt = None,
    cwd: CwdOpt = None,
    timeout: TimeoutOpt = 30.0,
) -> None:
    """Generate Markdown reference docs for the server's tools, resources and prompts."""

    async def go() -> str:
        async with connect(_target(target, transport, header, env, cwd), timeout=timeout) as c:
            return to_markdown(await gather(c))

    md = _run(go())
    if output:
        output.write_text(md, encoding="utf-8")
        err.print(f"wrote {output}")
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    app()
