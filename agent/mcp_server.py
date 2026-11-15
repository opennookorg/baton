"""MCP server exposing Baton's triage tools over baton.service, on stdio or read-only streamable HTTP."""

import argparse
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from baton import service
from baton.models import Issue

INSTRUCTIONS = (
    "Baton routes GitHub issues to the team that owns them, using a graph learned from past issues. "
    "Call route_issue first. If its confidence is under 0.6, check similar_past_issues, reporter_history "
    "and team_profile for the top candidates. Only name teams that appear in tool results."
)

def _call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a service function and turn any failure into a readable tool error."""
    try:
        return fn(*args)
    except NotImplementedError:
        raise ToolError(f"Baton backend is not ready yet: {fn.__name__} is not implemented.") from None
    except Exception as error:
        raise ToolError(f"{fn.__name__} failed: {type(error).__name__}: {error}") from None


def route_issue(title: str, body: str) -> dict:
    """Route an issue through the Baton graph."""
    return _call(service.route_issue, title, body).to_dict()


def similar_past_issues(title: str, body: str) -> dict:
    """List past issues most similar to the given one."""
    return {"issues": _call(service.similar_past_issues, title, body)}


def reporter_history(username: str) -> dict:
    """List teams that fixed this reporter's earlier issues."""
    return {"username": username, "teams": _call(service.reporter_history, username)}


def team_profile(team: str) -> dict:
    """List the entities most strongly linked to a team."""
    return {"team": team, "entities": _call(service.team_profile, team)}


def record_outcome(number: int, title: str, body: str, reporter: str, created_at: str, team: str) -> dict:
    """Feed a confirmed team back into the graph."""
    if not team.strip():
        raise ToolError("team must be a non-empty team name.")
    issue = Issue(number=number, title=title, body=body, created_at=created_at, reporter=reporter, sigs=(team,))
    return _call(service.record_outcome, issue, team)


TOOLS = {
    route_issue: (
        "Route an issue to its owning team. Give the issue title and body. Returns up to 3 ranked teams, each "
        "with its share of the score and the graph path (node names from issue signal to team) that explains it, "
        "plus an overall confidence from 0 to 1 and how many signals were known or unknown to the graph. "
        "Call this first for every issue."
    ),
    similar_past_issues: (
        "Find past issues that share the most signals (components, paths, error strings, words) with this one. "
        "Returns each past issue's number, title, the team that fixed it and the shared signal names. "
        "Use it when route_issue confidence is low."
    ),
    reporter_history: (
        "Look up which teams fixed earlier issues filed by this GitHub username, with counts. "
        "Reporters often file into the same area again. Use it when route_issue confidence is low."
    ),
    team_profile: (
        "Show the signals (components, paths, errors, words) most strongly linked to a team, with their kind and "
        "link strength. Use it to check whether a candidate team from route_issue really owns what the issue "
        "is about. Pass a team name exactly as route_issue returned it."
    ),
    record_outcome: (
        "Record the real owning team of an issue once it is known, so the graph learns from it. This writes to "
        "the graph: call it only when a human has confirmed the team, never with your own guess. Needs the issue "
        "number, title, body, reporter username, created_at (ISO 8601) and the confirmed team. Returns what changed."
    ),
}
WRITE_TOOLS = (record_outcome,)
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def build_server(read_only: bool = False) -> MCPServer:
    """An MCP server with all five tools, or only the four read tools when `read_only` is set."""
    server = MCPServer("baton", instructions=INSTRUCTIONS)
    for fn, description in TOOLS.items():
        if not (read_only and fn in WRITE_TOOLS):
            server.add_tool(fn, description=description)
    return server


mcp = build_server()


def serve_http(port: int, allowed_hosts: list[str]) -> None:
    """Serve only the read tools over streamable HTTP, accepting local hosts plus the given tunnel hosts."""
    security = TransportSecuritySettings(
        allowed_hosts=[f"{host}:*" for host in LOCAL_HOSTS] + allowed_hosts,
        allowed_origins=[f"http://{host}:*" for host in LOCAL_HOSTS] + [f"https://{host}" for host in allowed_hosts] + ["https://chatgpt.com"],
    )
    build_server(read_only=True).run("streamable-http", port=port, stateless_http=True, transport_security=security)


def main() -> None:
    """Run on stdio by default, or on read-only HTTP with --http."""
    parser = argparse.ArgumentParser(description="Baton MCP server")
    parser.add_argument("--http", action="store_true", help="serve read-only tools over streamable HTTP at /mcp")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST", help="public tunnel host to accept, repeatable")
    args = parser.parse_args()
    if args.http:
        serve_http(args.port, args.allow_host)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
