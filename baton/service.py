"""The one facade the API (app/server.py) and the MCP server (agent/mcp_server.py) call."""

import json
import threading
from collections import Counter
from functools import cache
from pathlib import Path

from baton import db, snapshots
from baton.config import CURVE_FILE, ISSUE_ID_BASE, RESULTS_DIR, SNAPSHOT_POINTS, LearnParams, Techniques
from baton.entities import KINDS_BY_PREFIX, display_name, kind_of
from baton.ids import IdTable
from baton.learn import Learner
from baton.models import Issue, RouteResult
from baton.router import known_entities, route, route_state
from baton.snapshots import GraphState

LIVE_STATE_FILE = RESULTS_DIR / "live_state.json"
LIVE_TECHNIQUES = Techniques(reweight=True, shortcuts=True, merging=False, splitting=False, gap_filling=False)
GRAPH_ISSUES = 25
learn_lock = threading.Lock()


@cache
def table() -> IdTable:
    """The name-to-ID table, loaded on first use."""
    return IdTable.load()


@cache
def snapshot(as_of: int) -> GraphState:
    """The graph mirror after `as_of` learning issues."""
    if as_of not in SNAPSHOT_POINTS:
        raise ValueError(f"as_of must be one of {SNAPSHOT_POINTS}")
    return snapshots.load(as_of)


@cache
def learner() -> Learner:
    """The live learner, resumed from the last saved live state or the final curve snapshot."""
    if LIVE_STATE_FILE.exists():
        state = GraphState.from_json(json.loads(LIVE_STATE_FILE.read_text()))
    elif snapshots.snapshot_path(SNAPSHOT_POINTS[-1]).exists():
        state = snapshots.load(SNAPSHOT_POINTS[-1])
    else:
        state = GraphState()
    return Learner(table(), LIVE_TECHNIQUES, LearnParams(), state)


def resolve(entity: str) -> str | None:
    """The vocabulary name for a prefixed or bare entity name, trying kinds in prefix order."""
    names = table().entities
    if entity in names:
        return entity
    return next((prefix + entity for prefix in KINDS_BY_PREFIX if prefix + entity in names), None)


def route_issue(title: str, body: str, reporter: str = "", as_of: int | None = None) -> RouteResult:
    """Route an issue live through HydraDB, or score against the snapshot at `as_of` learning issues."""
    if as_of is None:
        return route(title, body, reporter, table())
    return route_state(snapshot(as_of), title, body, reporter, table()).result


def record_outcome(issue: Issue, team: str) -> dict:
    """Apply one learning step for an issue whose real team is now known; returns what changed."""
    if team not in table().teams:
        raise ValueError(f"unknown team {team!r}")
    with learn_lock:
        live = learner()
        outcome = live.learn(issue, [team])
        LIVE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_STATE_FILE.write_text(json.dumps(live.state.to_json(), separators=(",", ":")) + "\n")
    keys = ("issue", "predicted", "correct", "links_reweighted", "shortcuts_created", "merges")
    return {"team": team, **{key: outcome[key] for key in keys}}


def curve() -> dict:
    """Return results/curve.json: {"lines": {name: [{"issues": n, "top1": f, "top3": f}, ...]}}."""
    if not CURVE_FILE.exists():
        return {"lines": {}}
    return {"lines": json.loads(Path(CURVE_FILE).read_text())["lines"]}


def graph_around(entity: str) -> dict:
    """Return {"nodes": [{id, name, label, kind}], "links": [{source, target, type, strength, shortcut}]} around one entity."""
    name = resolve(entity)
    if name is None:
        return {"nodes": [], "links": []}
    ids, state = table(), learner().state
    nodes: dict[int, dict] = {}
    links: list[dict] = []

    def entity_node(entity_name: str) -> int:
        node_id = ids.entities[entity_name]
        nodes[node_id] = {"id": node_id, "name": display_name(entity_name), "label": "Entity", "kind": kind_of(entity_name)}
        return node_id

    def team_node(team: str) -> int:
        node_id = ids.teams[team]
        nodes[node_id] = {"id": node_id, "name": team, "label": "Team", "kind": None}
        return node_id

    def link(source: int, target: int, kind: str, strength: float, shortcut: bool = False) -> None:
        links.append({"source": source, "target": target, "type": kind, "strength": round(strength, 3), "shortcut": shortcut})

    center = entity_node(name)
    for team, route_link in sorted(state.routes_out.get(name, {}).items()):
        link(center, team_node(team), "ROUTES_TO", route_link.strength, route_link.shortcut)
    for number in sorted(state.seen_in.get(name, ()), reverse=True)[:GRAPH_ISSUES]:
        issue_id = ISSUE_ID_BASE + number
        nodes[issue_id] = {"id": issue_id, "name": f"#{number}", "label": "Issue", "kind": None}
        link(center, issue_id, "SEEN_IN", 1.0)
        for team in state.history[number].teams:
            link(issue_id, team_node(team), "OWNED_BY", 1.0)
    for other in sorted(state.same_as_out.get(name, ())):
        link(center, entity_node(other), "SAME_AS", 1.0)
    return {"nodes": list(nodes.values()), "links": links}


def stats() -> dict:
    """Return node and link counts plus issues_learned, links_reweighted, merges, shortcuts, misroutes_avoided."""
    counts = db.counts()
    counters = learner().state.counters
    summary = json.loads(CURVE_FILE.read_text()).get("meta", {}).get("summary", {}) if CURVE_FILE.exists() else {}
    return {
        "nodes": sum(counts["nodes"].values()),
        "links": sum(counts["links"].values()),
        "teams": counts["nodes"]["Team"],
        "entities": counts["nodes"]["Entity"],
        "issues": counts["nodes"]["Issue"],
        "issues_learned": counters["issues_learned"],
        "links_reweighted": counters["links_reweighted"],
        "merges": counters["merges"],
        "shortcuts": counters["shortcuts"],
        "misroutes_avoided": int(summary.get("misroutes_avoided_per_1000", 0)),
    }


def similar_past_issues(title: str, body: str, limit: int = 5) -> list[dict]:
    """Return past issues sharing the most entities: [{number, title, team, shared: [names]}]."""
    state = learner().state
    known, _ = known_entities(title, body, "", table())
    shared: dict[int, list[str]] = {}
    for name in dict.fromkeys(known):
        for number in state.seen_in.get(name, ()):
            shared.setdefault(number, []).append(display_name(name))
    ranked = sorted(shared, key=lambda number: (-len(shared[number]), -number))[:limit]
    return [
        {"number": n, "title": state.history[n].title, "team": ", ".join(state.history[n].teams), "shared": shared[n]} for n in ranked
    ]


def reporter_history(username: str) -> list[dict]:
    """Return teams that fixed this reporter's earlier issues: [{team, count}]."""
    name = f"user:{username.lower()}"
    counts = Counter({team: n for (entity, team), n in learner().state.history_paths.items() if entity == name})
    return [{"team": team, "count": count} for team, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def team_profile(team: str, limit: int = 15) -> list[dict]:
    """Return the entities most strongly linked to a team: [{entity, kind, strength}]."""
    links = [(entity, link) for (entity, linked_team), link in learner().state.routes.items() if linked_team == team]
    ranked = sorted(links, key=lambda item: (-item[1].strength, item[0]))[:limit]
    return [{"entity": display_name(entity), "kind": kind_of(entity), "strength": round(link.strength, 3)} for entity, link in ranked]
