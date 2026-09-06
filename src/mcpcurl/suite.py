"""Smoke checks and YAML-driven test cases for an MCP server.

A suite file looks like::

    cases:
      - name: adds two numbers
        tool: add
        args: {a: 2, b: 3}
        expect:
          equals: 5
      - name: rejects bad input
        tool: add
        args: {a: "x", b: 1}
        expect:
          error: true
      - resource: "greeting://world"
        expect:
          text_contains: "Hello"
      - prompt: summarize
        args: {topic: "MCP"}
        expect:
          text_contains: "MCP"

Every ``expect`` key is optional. Supported keys: ``error`` (bool, default
false), ``equals`` (compared to the structured result, else to the first text
block parsed as JSON, else to the raw text), ``text_contains`` (substring or
list of substrings), ``max_ms`` (latency budget).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, ValidationError, validate
from jsonschema.exceptions import SchemaError

from .compat import attr, resource_uri
from .connect import Connection
from .inventory import Inventory, gather
from .render import result_text


@dataclass(slots=True)
class CaseResult:
    name: str
    ok: bool
    message: str = ""
    duration_ms: float = 0.0
    kind: str = "case"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "kind": self.kind,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass(slots=True)
class Suite:
    cases: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> Suite:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cases = data.get("cases") if isinstance(data, dict) else data
        if not isinstance(cases, list):
            raise ValueError("suite must contain a top-level 'cases' list")
        for i, case in enumerate(cases):
            if not isinstance(case, dict):
                raise ValueError(f"case {i} is not a mapping")
            if not any(k in case for k in ("tool", "resource", "prompt")):
                raise ValueError(f"case {i} needs one of: tool, resource, prompt")
        return cls(cases=cases)


def smoke_checks(inv: Inventory) -> list[CaseResult]:
    """Static checks that need no tool calls: unique names, valid schemas, docs."""
    results: list[CaseResult] = []
    names = [t.name for t in inv.tools]
    dupes = sorted({n for n in names if names.count(n) > 1})
    results.append(
        CaseResult(
            "tool names are unique",
            not dupes,
            f"duplicates: {', '.join(dupes)}" if dupes else f"{len(names)} tools",
            kind="smoke",
        )
    )
    for t in inv.tools:
        try:
            Draft202012Validator.check_schema(attr(t, "input_schema") or {})
            ok, msg = True, ""
        except SchemaError as exc:
            ok, msg = False, exc.message
        results.append(CaseResult(f"{t.name}: input schema is valid", ok, msg, kind="smoke"))
        results.append(
            CaseResult(
                f"{t.name}: has a description",
                bool((t.description or "").strip()),
                "" if t.description else "LLMs pick tools by description; add one",
                kind="smoke",
            )
        )
    return results


def coerce_args(tool_schema: dict[str, Any] | None, args: dict[str, Any]) -> dict[str, Any]:
    """Validate ``args`` against the tool's input schema client-side.

    Raises ``ValueError`` with the validator's message so a typo in a suite
    file is reported before a request ever hits the server.
    """
    if tool_schema:
        try:
            validate(args, tool_schema, cls=Draft202012Validator)
        except ValidationError as exc:
            path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
            raise ValueError(f"{path}: {exc.message}") from None
    return args


def parse_cli_value(raw: str) -> Any:
    """``--arg a=2`` becomes ``2``; ``--arg name=bob`` stays a string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def run_suite(
    conn: Connection,
    suite: Suite | None,
    *,
    smoke: bool = True,
    validate_args: bool = True,
) -> list[CaseResult]:
    inv = await gather(conn)
    results: list[CaseResult] = smoke_checks(inv) if smoke else []
    for i, case in enumerate(suite.cases if suite else []):
        results.append(await _run_case(conn, inv, case, i, validate_args=validate_args))
    return results


async def _run_case(
    conn: Connection,
    inv: Inventory,
    case: dict[str, Any],
    index: int,
    *,
    validate_args: bool,
) -> CaseResult:
    expect: dict[str, Any] = case.get("expect") or {}
    args: dict[str, Any] = case.get("args") or {}
    started = time.perf_counter()
    is_error = False
    text = ""
    value: Any = None

    try:
        if "tool" in case:
            name = case["tool"]
            label = case.get("name") or f"{name}({json.dumps(args, default=str)})"
            tool = inv.tool(name)
            if tool is None:
                return CaseResult(label, False, f"tool {name!r} not advertised by server")
            if validate_args:
                coerce_args(attr(tool, "input_schema"), args)
            result = await conn.session.call_tool(name, args)
            is_error = bool(attr(result, "is_error"))
            text = result_text(result)
            value = attr(result, "structured_content")
            if isinstance(value, dict) and set(value) == {"result"}:
                value = value["result"]
            if value is None:
                value = _first_json(text)
        elif "resource" in case:
            uri = case["resource"]
            label = case.get("name") or f"read {uri}"
            res = await conn.session.read_resource(resource_uri(uri))
            text = "\n".join(c.text for c in res.contents if getattr(c, "text", None) is not None)
            value = _first_json(text)
        else:
            name = case["prompt"]
            label = case.get("name") or f"prompt {name}"
            res = await conn.session.get_prompt(name, {k: str(v) for k, v in args.items()})
            text = "\n".join(
                m.content.text for m in res.messages if getattr(m.content, "text", None)
            )
            value = text
    except Exception as exc:  # noqa: BLE001 - report, do not crash the run
        duration = (time.perf_counter() - started) * 1000
        if expect.get("error") is True:
            return CaseResult(
                case.get("name") or f"case {index}", True, "raised as expected", duration
            )
        return CaseResult(
            case.get("name") or f"case {index}", False, f"{type(exc).__name__}: {exc}", duration
        )

    duration = (time.perf_counter() - started) * 1000
    problems = _check_expectations(expect, is_error=is_error, text=text, value=value, ms=duration)
    return CaseResult(label, not problems, "; ".join(problems), duration)


def _first_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _check_expectations(
    expect: dict[str, Any], *, is_error: bool, text: str, value: Any, ms: float
) -> list[str]:
    problems: list[str] = []
    want_error = bool(expect.get("error", False))
    if is_error != want_error:
        problems.append(
            f"expected {'an error' if want_error else 'success'}, got "
            f"{'error: ' + text[:120] if is_error else 'success'}"
        )
    if "equals" in expect and value != expect["equals"]:
        problems.append(f"expected {expect['equals']!r}, got {value!r}")
    contains = expect.get("text_contains")
    if contains is not None:
        needles = contains if isinstance(contains, list) else [contains]
        missing = [str(n) for n in needles if str(n) not in text]
        if missing:
            problems.append(f"text missing {missing}")
    if "max_ms" in expect and ms > float(expect["max_ms"]):
        problems.append(f"took {ms:.0f} ms, budget {expect['max_ms']} ms")
    return problems
