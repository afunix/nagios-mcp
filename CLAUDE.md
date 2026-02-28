# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`nagios-mcp` is a Model Context Protocol (MCP) server that exposes Nagios Core monitoring data as LLM-callable tools. It communicates with Nagios via its CGI JSON APIs (`statusjson.cgi` and `objectjson.cgi`).

## Development Commands

```bash
# Install dependencies
uv sync

# Run the server locally (STDIO transport)
uv run nagios-mcp --config nagios_config.yaml

# Run with SSE transport
uv run nagios-mcp --config nagios_config.yaml --transport sse --host localhost --port 8000

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Auto-fix lint issues
uv run ruff check --fix .

# Build for PyPI
python -m build
```

There are no automated tests in this project.

## Architecture

### Request Flow

1. MCP client calls a tool → `server.py:handle_call_tool()` → `tools/tools.py:handle_tool_calls()` dispatcher → `*_fn()` implementation → `utils.py:make_request()` → Nagios CGI

### Key Files

- **`nagios_mcp/server.py`** — Entry point logic: argument parsing, config loading, transport selection (stdio vs SSE via Starlette/uvicorn), and MCP server setup. Registers `list_tools` and `call_tool` handlers.
- **`nagios_mcp/tools/tools.py`** — Two responsibilities: (1) `types.Tool` schema definitions for all MCP tools, (2) `handle_tool_calls()` — a large if/elif dispatcher that routes tool name → `*_fn()` calls and returns `List[types.TextContent]`.
- **`nagios_mcp/tools/status_tools.py`** — Implementations for status queries (`statusjson.cgi`): host status, service status, alerts, health summary, unhandled problems, group-scoped queries.
- **`nagios_mcp/tools/config_tools.py`** — Implementations for config/object queries (`objectjson.cgi`): object lists, single object config, dependencies, contacts, comments, downtimes.
- **`nagios_mcp/tools/utils.py`** — Shared global state: `NAGIOS_URL`, `NAGIOS_USER`, `session`, OAuth2 token cache. `initialize_nagios_config()` sets up the `requests.Session` with SSL and eagerly fetches the first OAuth2 token. `_fetch_token()` / `_get_valid_token()` manage token refresh (proactive 30s buffer + 401-triggered retry). `make_request()` performs all HTTP calls with `Authorization: Bearer` headers and parses Nagios CGI JSON responses (checks `result.type_code == 0` for success, returns `data` dict).

### Adding a New Tool

1. Add a `types.Tool(...)` definition in `tools/tools.py`
2. Implement the `*_fn()` function in `status_tools.py` (for `statusjson.cgi`) or `config_tools.py` (for `objectjson.cgi`)
3. Add an `elif tool_name == "..."` branch in `handle_tool_calls()` in `tools/tools.py`
4. Export from `tools/__init__.py`
5. Register in `server.py:handle_list_tools()`

### Configuration

The server requires a YAML or JSON config file with:
```yaml
nagios_url: "https://your-nagios-host/nagios"
nagios_user: "your_keycloak_username"
client_id: "your_oauth2_client_id"
oauth_token_url: "https://keycloak.example.com/auth/realms/myrealm/protocol/openid-connect/token"
ca_cert_path: ""  # path to CA cert bundle for HTTPS, or empty string
```

Secrets are passed via environment variables (not the config file):
- `NAGIOS_PASS` — Keycloak password for `nagios_user`
- `NAGIOS_CLIENT_SECRET` — OAuth2 client secret for `client_id`

The server exits at startup with a clear error if either env var is missing or if the initial token fetch fails (bad credentials).

### Transport Modes

- **stdio** (default): Used by MCP clients like Claude Desktop. Communicates over stdin/stdout.
- **SSE**: HTTP server via Starlette + uvicorn. SSE endpoint at `/sse`, message post at `/messages`.

## Code Style

Ruff is configured (`line-length = 88`, double quotes, space indent). Rules: E4, E7, E9, F (pyflakes), I (isort). Run `ruff check --fix .` before committing.

## Publishing

Pushing to `main` or a `v*` tag triggers the GitHub Actions workflow to publish to PyPI (if version in `pyproject.toml` is new). Bump `version` in `pyproject.toml` before release.
