"""The one facade the API (app/server.py) and the MCP server (agent/mcp_server.py) call."""

from baton.models import Issue, RouteResult


def route_issue(title: str, body: str, reporter: str = "", as_of: int | None = None) -> RouteResult:
    """Route an issue live through HydraDB, or score against the snapshot at `as_of` learning issues."""
    raise NotImplementedError


def record_outcome(issue: Issue, team: str) -> dict:
    """Apply one learning step for an issue whose real team is now known; returns what changed."""
    raise NotImplementedError


def curve() -> dict:
    """Return results/curve.json: {"lines": {name: [{"issues": n, "top1": f, "top3": f}, ...]}}."""
    raise NotImplementedError


def graph_around(entity: str) -> dict:
    """Return {"nodes": [{id, name, label, kind}], "links": [{source, target, type, strength, shortcut}]} around one entity."""
    raise NotImplementedError


def stats() -> dict:
    """Return node and link counts plus issues_learned, links_reweighted, merges, shortcuts, misroutes_avoided."""
    raise NotImplementedError


def similar_past_issues(title: str, body: str, limit: int = 5) -> list[dict]:
    """Return past issues sharing the most entities: [{number, title, team, shared: [names]}]."""
    raise NotImplementedError


def reporter_history(username: str) -> list[dict]:
    """Return teams that fixed this reporter's earlier issues: [{team, count}]."""
    raise NotImplementedError


def team_profile(team: str, limit: int = 15) -> list[dict]:
    """Return the entities most strongly linked to a team: [{entity, kind, strength}]."""
    raise NotImplementedError
