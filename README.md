# mcpcurl

[![CI](https://github.com/peroksai2-arch/mcpcurl/actions/workflows/ci.yml/badge.svg)](https://github.com/peroksai2-arch/mcpcurl/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`curl` for [Model Context Protocol](https://modelcontextprotocol.io) servers.
List what a server exposes, call a tool with arguments checked against its
schema, run a YAML test suite in CI, and generate Markdown docs. Works with
stdio, Streamable HTTP and SSE servers.

```bash
pip install mcpcurl

mcpcurl list "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcpcurl list http://localhost:8000/mcp
mcpcurl call "python server.py" add -a a=2 -a b=3
mcpcurl test "python server.py" --suite tests/mcp.yaml     # exit 1 on failure
mcpcurl docs "python server.py" -o TOOLS.md
```

## Why

Developing an MCP server today means restarting an LLM client every time you
want to know whether your tool shows up, whether its schema is what you think
it is, or whether it errors. That is slow, and it does not fit in CI.
`mcpcurl` talks the protocol directly so you can:

- see the exact tool list, argument signatures and descriptions the model sees
- call a tool from a shell with typed arguments (`--arg n=3` sends an integer)
- fail a pull request when a tool loses its description or its schema breaks
- keep a `TOOLS.md` in the repo that is generated, not hand-maintained

## Commands

### `list`

```
$ mcpcurl list "python tests/sample_server.py"
sample v1.27.0  protocol 2025-11-25
A toy server with one of everything.

                                  Tools (5)
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ name         ┃ arguments                       ┃ description                         ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ add          │ a: integer, b: integer          │ Add two integers.                   │
│ echo         │ text: string, upper?: boolean   │ Return the text, optionally upper-… │
│ fail         │ message?: string                │ Always raises, to exercise error r… │
│ slow         │ seconds?: number                │ Sleep for a while, to exercise lat… │
│ undocumented │ x: integer                      │                                     │
└──────────────┴──────────────┴──────────────────┴─────────────────────────────────────┘
```

`--json` prints the full inventory including raw JSON schemas. `-v` shows
complete descriptions.

### `call`

```bash
mcpcurl call "python server.py" echo -a text=hi -a upper=true
mcpcurl call "python server.py" search -j '{"query": "mcp", "limit": 5}'
```

Values passed with `--arg` are parsed as JSON when possible, so `n=3` is an
integer and `tags='["a","b"]'` is a list. Arguments are validated against the
tool's `inputSchema` before the request is sent; a mismatch exits with code 2
and the validator's message instead of a vague server error. Pass
`--no-validate` to send anyway. Exit code 1 means the server returned
`isError: true`.

### `test`

```yaml
# tests/mcp.yaml
cases:
  - name: adds two numbers
    tool: add
    args: { a: 2, b: 3 }
    expect: { equals: 5, max_ms: 500 }

  - name: rejects bad input
    tool: add
    args: { a: "x", b: 1 }
    expect: { error: true }

  - resource: "greeting://world"
    expect: { text_contains: "Hello, world" }

  - prompt: summarize
    args: { topic: MCP }
    expect: { text_contains: MCP }
```

```
$ mcpcurl test "python server.py" --suite tests/mcp.yaml
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ check                                ┃      ms ┃ detail                              ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ok │ tool names are unique                │         │ 5 tools                             │
│ ok │ add: input schema is valid           │         │                                     │
│ ok │ add: has a description               │         │                                     │
│ FAIL │ undocumented: has a description    │         │ LLMs pick tools by description; ad… │
│ ok │ adds two numbers                     │      41 │                                     │
│ ok │ rejects bad input                    │       2 │ raised as expected                  │
│ ok │ read greeting://world                │       6 │                                     │
│ ok │ prompt summarize                     │       5 │                                     │
└────┴──────────────────────────────────────┴─────────┴─────────────────────────────────────┘
15 passed, 1 failed
```

Smoke checks run before the suite and need no configuration: unique tool
names, every `inputSchema` is a valid JSON Schema, every tool has a
description. Disable with `--no-smoke`. `--json` emits one object per check
for other tooling.

Supported `expect` keys:

| key             | meaning                                                                 |
|-----------------|-------------------------------------------------------------------------|
| `error`         | `true` if the call should fail (server error or exception)               |
| `equals`        | compared with the structured result, else the text parsed as JSON       |
| `text_contains` | substring or list of substrings that must appear in the text content    |
| `max_ms`        | latency budget                                                          |

### `docs`

Generates a Markdown reference with one section per tool, an argument table
built from the schema, plus resources and prompts. Commit the output or
publish it; regenerate in CI to catch drift.

### `read` and `prompt`

`mcpcurl read TARGET uri` prints a resource. `mcpcurl prompt TARGET name -a k=v`
renders a prompt's messages.

## Targets and transports

| target                                 | transport       |
|----------------------------------------|-----------------|
| `"python server.py"`, `"npx -y pkg"`   | stdio           |
| `http://host/mcp`                      | Streamable HTTP |
| `http://host/sse`                      | SSE             |

Override detection with `-t stdio|http|sse`. Add `-H Authorization=Bearer x`
for HTTP headers and `-e KEY=VALUE` to set environment variables for stdio
servers. `--cwd` sets the working directory of a stdio server.

## GitHub Actions

```yaml
- run: pip install mcpcurl
- run: mcpcurl test "python server.py" --suite tests/mcp.yaml
```

## Python API

```python
from mcpcurl import Target, connect, gather, run_suite, Suite

async with connect(Target("python server.py")) as conn:
    inventory = await gather(conn)
    results = await run_suite(conn, Suite.load("tests/mcp.yaml"))
```

## Development

```bash
pip install -e ".[dev]"
ruff check . && pytest
```

Tests spawn `tests/sample_server.py` over stdio, so they exercise the real
transport on Linux and Windows.

## License

MIT
