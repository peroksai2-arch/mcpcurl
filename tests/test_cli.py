from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mcpcurl.cli import app

runner = CliRunner()


def test_list_human(server_cmd: str) -> None:
    result = runner.invoke(app, ["list", server_cmd])
    assert result.exit_code == 0, result.output
    assert "sample" in result.output
    assert "add" in result.output
    assert "greeting://{name}" in result.output


def test_list_json(server_cmd: str) -> None:
    result = runner.invoke(app, ["list", server_cmd, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["server"]["name"] == "sample"
    assert {t["name"] for t in data["tools"]} >= {"add", "echo"}


def test_call_parses_json_values_and_validates(server_cmd: str) -> None:
    ok = runner.invoke(app, ["call", server_cmd, "add", "-a", "a=2", "-a", "b=40", "--json"])
    assert ok.exit_code == 0, ok.output
    assert json.loads(ok.output)["content"] == [42]

    bad = runner.invoke(app, ["call", server_cmd, "add", "-a", "a=x", "-a", "b=1"])
    assert bad.exit_code == 2
    assert "invalid arguments" in bad.output

    unknown = runner.invoke(app, ["call", server_cmd, "nope"])
    assert unknown.exit_code == 2
    assert "unknown tool" in unknown.output


def test_call_server_error_exits_1(server_cmd: str) -> None:
    result = runner.invoke(app, ["call", server_cmd, "fail", "-j", '{"message": "kaput"}'])
    assert result.exit_code == 1
    # mcp 1.x includes the exception message, 2.x only names the tool.
    assert "Error executing tool fail" in result.output


def test_read_and_prompt(server_cmd: str) -> None:
    read = runner.invoke(app, ["read", server_cmd, "greeting://cli"])
    assert read.exit_code == 0, read.output
    assert "Hello, cli!" in read.output

    prompt = runner.invoke(app, ["prompt", server_cmd, "summarize", "-a", "topic=probes"])
    assert prompt.exit_code == 0, prompt.output
    assert "Summarise probes" in prompt.output


def test_test_command_exit_codes(server_cmd: str, tmp_path: Path) -> None:
    # Smoke alone fails because `undocumented` has no description.
    smoke = runner.invoke(app, ["test", server_cmd, "--json"])
    assert smoke.exit_code == 1
    failed = [r["name"] for r in json.loads(smoke.output) if not r["ok"]]
    assert failed == ["undocumented: has a description"]

    human = runner.invoke(app, ["test", server_cmd])
    assert human.exit_code == 1
    assert "1 failed" in human.output

    suite = tmp_path / "s.yaml"
    suite.write_text("cases:\n  - tool: add\n    args: {a: 1, b: 1}\n    expect: {equals: 2}\n")
    passing = runner.invoke(
        app, ["test", server_cmd, "--suite", str(suite), "--no-smoke", "--json"]
    )
    assert passing.exit_code == 0, passing.output
    data = json.loads(passing.output)
    assert data == [
        {
            "name": data[0]["name"],
            "ok": True,
            "kind": "case",
            "message": "",
            "duration_ms": data[0]["duration_ms"],
        }
    ]


def test_docs_to_file(server_cmd: str, tmp_path: Path) -> None:
    out = tmp_path / "TOOLS.md"
    result = runner.invoke(app, ["docs", server_cmd, "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("# sample")


def test_bad_command_exits_2() -> None:
    result = runner.invoke(app, ["list", "definitely-not-a-real-binary-xyz"])
    assert result.exit_code == 2



def test_bearer_env_fallback(monkeypatch) -> None:
    from mcpcurl.cli import _target

    monkeypatch.setenv("MCPCURL_BEARER", "from-env")
    target = _target("https://example.com/mcp", "auto", None, None, None)

    assert target.headers["Authorization"] == "Bearer from-env"


def test_explicit_authorization_header_beats_env(monkeypatch) -> None:
    from mcpcurl.cli import _target

    monkeypatch.setenv("MCPCURL_BEARER", "from-env")
    target = _target(
        "https://example.com/mcp",
        "auto",
        ["Authorization=Custom token"],
        None,
        None,
    )

    assert target.headers["Authorization"] == "Custom token"


def test_bearer_option_beats_authorization_header(monkeypatch) -> None:
    from mcpcurl.cli import _target

    monkeypatch.setenv("MCPCURL_BEARER", "from-env")
    target = _target(
        "https://example.com/mcp",
        "auto",
        ["Authorization=Custom token"],
        None,
        None,
        "explicit",
    )

    assert target.headers["Authorization"] == "Bearer explicit"



def test_lowercase_authorization_header_beats_env(monkeypatch) -> None:
    from mcpcurl.cli import _target

    monkeypatch.setenv("MCPCURL_BEARER", "from-env")
    target = _target(
        "https://example.com/mcp",
        "auto",
        ["authorization=Custom token"],
        None,
        None,
    )

    assert target.headers == {"authorization": "Custom token"}


def test_bearer_option_replaces_lowercase_authorization(monkeypatch) -> None:
    from mcpcurl.cli import _target

    target = _target(
        "https://example.com/mcp",
        "auto",
        ["authorization=Custom token"],
        None,
        None,
        "explicit",
    )

    assert target.headers == {"Authorization": "Bearer explicit"}
