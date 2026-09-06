from __future__ import annotations

from mcpcurl import Target, connect, gather
from mcpcurl.compat import attr
from mcpcurl.render import schema_summary, to_markdown


async def test_gather_lists_everything(server_cmd: str) -> None:
    async with connect(Target(server_cmd)) as conn:
        inv = await gather(conn)

    assert inv.server_name == "sample"
    assert inv.instructions and "toy server" in inv.instructions
    assert {t.name for t in inv.tools} == {"add", "echo", "fail", "slow", "undocumented"}
    assert [str(r.uri) for r in inv.resources] == ["info://about"]
    assert [attr(r, "uri_template") for r in inv.resource_templates] == ["greeting://{name}"]
    assert [p.name for p in inv.prompts] == ["summarize"]

    add = inv.tool("add")
    assert add is not None
    assert attr(add, "input_schema")["required"] == ["a", "b"]


def test_target_transport_detection() -> None:
    assert Target("python x.py").resolved_transport() == "stdio"
    assert Target("http://localhost:8000/mcp").resolved_transport() == "http"
    assert Target("https://host/sse").resolved_transport() == "sse"
    assert Target("https://host/sse", transport="http").resolved_transport() == "http"


def test_schema_summary_marks_optional_arguments() -> None:
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "upper": {"type": "boolean"},
            "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
        "required": ["text"],
    }
    assert schema_summary(schema) == "text: string, upper?: boolean, n?: integer|null"
    assert schema_summary(None) == ""


async def test_markdown_docs(server_cmd: str) -> None:
    async with connect(Target(server_cmd)) as conn:
        md = to_markdown(await gather(conn))
    assert md.startswith("# sample\n")
    assert "### `add`" in md
    assert "| `a` | integer | yes |" in md
    assert "| `upper` | boolean | no |" in md
    assert "`greeting://{name}`" in md
    assert "### `summarize`" in md
    assert "| `topic` | yes |" in md


async def test_inventory_to_dict_is_json_friendly(server_cmd: str) -> None:
    import json

    async with connect(Target(server_cmd)) as conn:
        data = (await gather(conn)).to_dict()
    json.dumps(data)  # must not raise
    assert data["server"]["name"] == "sample"
    assert any(t["name"] == "echo" for t in data["tools"])
