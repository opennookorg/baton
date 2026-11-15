"""MCP tool tests against a monkeypatched fake baton.service."""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import Client, StdioServerParameters

from agent import mcp_server
from baton import service
from baton.models import Issue, RouteResult, TeamScore

ROOT = Path(__file__).resolve().parent.parent
TOOL_NAMES = {"route_issue", "similar_past_issues", "reporter_history", "team_profile", "record_outcome"}


def call(name: str, arguments: dict):
    """Call one tool through an in-memory MCP client."""

    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(run)


def payload(result) -> dict:
    """Decode the JSON text content of a successful tool result."""
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


@pytest.fixture
def fake_service(monkeypatch):
    recorded = {}

    def route_issue(title, body, reporter="", as_of=None):
        return RouteResult(
            teams=[TeamScore("sig-node", 0.7, ["kubelet", "sig-node"]), TeamScore("sig-storage", 0.3, ["pv", "sig-storage"])],
            confidence=0.7,
            entities_found=2,
            entities_unknown=1,
        )

    def record_outcome(issue, team):
        recorded["issue"], recorded["team"] = issue, team
        return {"links_reweighted": 3}

    monkeypatch.setattr(service, "route_issue", route_issue)
    monkeypatch.setattr(service, "record_outcome", record_outcome)
    monkeypatch.setattr(service, "similar_past_issues", lambda t, b, limit=5: [{"number": 9, "title": "x", "team": "sig-node", "shared": ["kubelet"]}])
    monkeypatch.setattr(service, "reporter_history", lambda u: [{"team": "sig-node", "count": 4}])
    monkeypatch.setattr(service, "team_profile", lambda t, limit=15: [{"entity": "kubelet", "kind": "component", "strength": 0.9}])
    return recorded


def test_lists_exactly_five_tools():
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()

    tools = anyio.run(run).tools
    assert {tool.name for tool in tools} == TOOL_NAMES
    assert all(tool.description for tool in tools)


def test_route_issue_shape(fake_service):
    data = payload(call("route_issue", {"title": "kubelet crash", "body": "panic"}))
    assert data["confidence"] == 0.7
    assert data["teams"][0] == {"team": "sig-node", "share": 0.7, "path": ["kubelet", "sig-node"]}
    assert data["entities_found"] == 2 and data["entities_unknown"] == 1


def test_read_tool_shapes(fake_service):
    assert payload(call("similar_past_issues", {"title": "a", "body": "b"}))["issues"][0]["team"] == "sig-node"
    assert payload(call("reporter_history", {"username": "alice"})) == {"username": "alice", "teams": [{"team": "sig-node", "count": 4}]}
    assert payload(call("team_profile", {"team": "sig-node"}))["entities"][0]["entity"] == "kubelet"


def test_record_outcome_builds_issue(fake_service):
    args = {"number": 5, "title": "t", "body": "b", "reporter": "alice", "created_at": "2026-01-01T00:00:00Z", "team": "sig-node"}
    assert payload(call("record_outcome", args)) == {"links_reweighted": 3}
    assert fake_service["issue"] == Issue(5, "t", "b", "2026-01-01T00:00:00Z", "alice", ("sig-node",))
    assert fake_service["team"] == "sig-node"


def test_record_outcome_rejects_blank_team(fake_service):
    args = {"number": 5, "title": "t", "body": "b", "reporter": "alice", "created_at": "2026-01-01", "team": " "}
    result = call("record_outcome", args)
    assert result.is_error and "team" in result.content[0].text


def test_not_implemented_becomes_readable_error(monkeypatch):
    def not_ready(title, body):
        raise NotImplementedError

    monkeypatch.setattr(service, "route_issue", not_ready)
    result = call("route_issue", {"title": "a", "body": "b"})
    assert result.is_error
    assert "not ready yet" in result.content[0].text


def test_other_failures_become_readable_errors(monkeypatch):
    def broken(username):
        raise ConnectionError("HydraDB unreachable")

    monkeypatch.setattr(service, "reporter_history", broken)
    result = call("reporter_history", {"username": "alice"})
    assert result.is_error
    assert "ConnectionError: HydraDB unreachable" in result.content[0].text


def test_stdio_server_starts_and_lists_tools():
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent.mcp_server"], cwd=str(ROOT))

    async def run():
        with anyio.fail_after(30):
            async with Client(params) as client:
                return await client.list_tools()

    assert {tool.name for tool in anyio.run(run).tools} == TOOL_NAMES


@pytest.fixture
def http_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "agent.mcp_server", "--http", "--port", str(port), "--allow-host", "baton.example.com"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.2)
    yield url
    process.terminate()
    process.wait(10)


def test_http_server_serves_only_read_tools(http_server):
    async def run():
        with anyio.fail_after(30):
            async with Client(http_server) as client:
                return await client.list_tools()

    assert {tool.name for tool in anyio.run(run).tools} == TOOL_NAMES - {"record_outcome"}


def test_http_server_accepts_only_local_and_allowed_hosts(http_server):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    headers = {"Accept": "application/json, text/event-stream"}
    assert httpx.post(http_server, json=ping, headers={**headers, "Host": "evil.example.com"}).status_code == 421
    assert httpx.post(http_server, json=ping, headers={**headers, "Host": "baton.example.com"}).status_code == 200
