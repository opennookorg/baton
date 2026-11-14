# Baton triage agent

`agent/mcp_server.py` is a stdio MCP server (Python MCP SDK 2.x `MCPServer`, formerly FastMCP) over `baton.service`. It exposes five tools and nothing else, so an agent can read the graph only through them:

| Tool | Arguments | Returns |
|---|---|---|
| `route_issue` | `title`, `body` | `{teams: [{team, share, path}], confidence, entities_found, entities_unknown}` |
| `similar_past_issues` | `title`, `body` | `{issues: [{number, title, team, shared}]}` |
| `reporter_history` | `username` | `{username, teams: [{team, count}]}` |
| `team_profile` | `team` | `{team, entities: [{entity, kind, strength}]}` |
| `record_outcome` | `number`, `title`, `body`, `reporter`, `created_at`, `team` | what the learning step changed |

Failures (including the backend not being built yet) come back as tool errors with a readable message, never a crash.

The triage instructions live in [`TRIAGE.md`](TRIAGE.md).

## Claude Code

The repo root `.mcp.json` registers the server as `baton`. Start Claude Code from the repo root and approve the project server when asked. Verify:

```sh
claude mcp list
```

`baton` should show as connected. Inside a session, `/mcp` lists its five tools. To triage, start a session with the instructions loaded:

```sh
claude --append-system-prompt "$(cat agent/TRIAGE.md)"
```

## Codex

Add to `~/.codex/config.toml` (set `cwd` to your checkout):

```toml
[mcp_servers.baton]
command = "uv"
args = ["run", "python", "-m", "agent.mcp_server"]
cwd = "/path/to/baton"
```

Verify with `codex mcp list`, then `/mcp` inside a Codex session lists the five tools. Paste `agent/TRIAGE.md` as the first message, or put it in the session's instructions.

## Check without a client

```sh
uv run pytest tests/test_agent_mcp.py
```

`test_stdio_server_starts_and_lists_tools` launches the server as a subprocess over stdio and checks the tool list.

## Load test

`eval/loadtest.py` (Locust) measures `/route` while `/learn` writes. `RouteUser` posts test-split issues (newest 300 of `data/issues.jsonl` by `created_at`, or a built-in sample when the file is missing) to `POST /route`. `LearnUser` (2 users) posts learning-stream issues in date order to `POST /learn` as `{"issue": <issues.jsonl row>, "team": sigs[0]}`.

With the API running (`uv run uvicorn app.server:app --port 8000`):

```sh
uv run python -m eval.loadtest
```

That runs headless with 20 users (18 routing, 2 learning), spawn rate 5, for 60 s against http://localhost:8000, and writes median and p95 response times per endpoint to `results/loadtest.json`. Extra Locust flags override the defaults, for example `uv run python -m eval.loadtest -t 120s -H http://127.0.0.1:9000`.

`/learn` changes the graph, so run it against a graph you can rebuild.
