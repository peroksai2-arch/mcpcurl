from __future__ import annotations

from pathlib import Path

import pytest

from mcpcurl import Suite, Target, connect, gather, run_suite, smoke_checks
from mcpcurl.suite import coerce_args, parse_cli_value


async def test_smoke_checks_flag_missing_description(server_cmd: str) -> None:
    async with connect(Target(server_cmd)) as conn:
        results = smoke_checks(await gather(conn))
    by_name = {r.name: r for r in results}
    assert by_name["tool names are unique"].ok
    assert by_name["add: input schema is valid"].ok
    assert by_name["add: has a description"].ok
    assert not by_name["undocumented: has a description"].ok


async def test_yaml_suite_end_to_end(server_cmd: str, tmp_path: Path) -> None:
    suite_file = tmp_path / "suite.yaml"
    suite_file.write_text(
        """
cases:
  - name: adds
    tool: add
    args: {a: 2, b: 3}
    expect: {equals: 5, text_contains: "5", max_ms: 5000}
  - name: echo upper
    tool: echo
    args: {text: hi, upper: true}
    expect: {equals: HI}
  - name: server error is reported
    tool: fail
    args: {message: nope}
    expect: {error: true, text_contains: "Error executing tool fail"}
  - name: wrong expectation fails
    tool: add
    args: {a: 1, b: 1}
    expect: {equals: 3}
  - name: unknown tool fails
    tool: nope
  - name: schema mismatch is caught client-side
    tool: add
    args: {a: "x", b: 1}
  - resource: "greeting://world"
    expect: {text_contains: "Hello, world"}
  - prompt: summarize
    args: {topic: MCP}
    expect: {text_contains: MCP}
""",
        encoding="utf-8",
    )
    suite = Suite.load(suite_file)
    async with connect(Target(server_cmd)) as conn:
        results = await run_suite(conn, suite, smoke=False)

    outcome = {r.name: (r.ok, r.message) for r in results}
    assert outcome["adds"] == (True, "")
    assert outcome["echo upper"] == (True, "")
    assert outcome["server error is reported"] == (True, "")
    assert outcome["wrong expectation fails"][0] is False
    assert "expected 3, got 2" in outcome["wrong expectation fails"][1]
    assert "not advertised" in outcome["unknown tool fails"][1]
    assert "a:" in outcome["schema mismatch is caught client-side"][1]
    assert outcome["read greeting://world"] == (True, "")
    assert outcome["prompt summarize"] == (True, "")


async def test_latency_budget(server_cmd: str) -> None:
    suite = Suite(cases=[{"tool": "slow", "args": {"seconds": 0.3}, "expect": {"max_ms": 50}}])
    async with connect(Target(server_cmd)) as conn:
        (result,) = await run_suite(conn, suite, smoke=False)
    assert not result.ok
    assert "budget 50" in result.message


def test_suite_load_rejects_bad_shapes(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases:\n  - name: no target\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs one of"):
        Suite.load(bad)
    bad.write_text("hello: world\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cases"):
        Suite.load(bad)


def test_coerce_args_reports_path() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    }
    assert coerce_args(schema, {"a": 1}) == {"a": 1}
    with pytest.raises(ValueError, match="a: 'x' is not of type 'integer'"):
        coerce_args(schema, {"a": "x"})
    with pytest.raises(ValueError, match="<root>: 'a' is a required property"):
        coerce_args(schema, {})


def test_parse_cli_value() -> None:
    assert parse_cli_value("2") == 2
    assert parse_cli_value("true") is True
    assert parse_cli_value('{"k": [1]}') == {"k": [1]}
    assert parse_cli_value("bob") == "bob"
