"""The one facade the API (app/server.py) and the MCP server (agent/mcp_server.py) call."""

import json
import threading
from collections import Counter
from functools import cache, wraps
from pathlib import Path

from baton import db, repos, snapshots
from baton.config import ISSUE_ID_BASE, RESULTS_DIR
from baton.entities import KINDS_BY_PREFIX, display_name, kind_of
from baton.ids import IdTable
from baton.learn import BATON_PARAMS, BATON_TECHNIQUES, Learner
from baton.models import Issue, RouteResult
from baton.repos import RepoProfile
from baton.router import known_entities, route, route_state
from baton.snapshots import GraphState

LIVE_STATE_FILE = RESULTS_DIR / "live_state.json"
LIVE_TECHNIQUES = BATON_TECHNIQUES
GRAPH_ISSUES = 25
learn_lock = threading.Lock()


def per_repo(function):
    """Run a service call against the repo named by its `repo` keyword (Kubernetes when omitted)."""

    @wraps(function)
    def call(*args, repo: str | None = None, **kwargs):
        with repos.use(repos.load(repo)):
            return function(*args, **kwargs)

    return call


def live_state_file(profile: RepoProfile) -> Path:
    """Where a repo's live learning state is saved between restarts."""
    return LIVE_STATE_FILE if profile.is_kubernetes else profile.live_state_file


@cache
def repo_saved_state(profile: RepoProfile) -> GraphState:
    """The repo's last saved live state, else its final curve snapshot, else an empty graph."""
    path, final = live_state_file(profile), profile.sizes.snapshots[-1]
    if path.exists():
        return GraphState.from_json(json.loads(path.read_text()))
    if snapshots.snapshot_path(final, profile.snapshot_dir).exists():
        return snapshots.load(final, profile.snapshot_dir)
    return GraphState()


@cache
def repo_table(profile: RepoProfile) -> IdTable:
    """The repo's name-to-ID table plus the entities its learner added, replayed in order so their IDs match the graph."""
    ids = IdTable.load(profile.table_file)
    for name in repo_saved_state(profile).added_entities:
        ids.add_entity(name)
    return ids


@cache
def repo_snapshot(profile: RepoProfile, as_of: int) -> GraphState:
    """The repo's graph mirror after `as_of` learning issues."""
    if as_of not in profile.sizes.snapshots:
        raise ValueError(f"as_of must be one of {list(profile.sizes.snapshots)} for {profile.repo}")
    return snapshots.load(as_of, profile.snapshot_dir)


@cache
def repo_learner(profile: RepoProfile) -> Learner:
    """The repo's live learner, resumed from its last saved live state or its final curve snapshot."""
    return Learner(repo_table(profile), LIVE_TECHNIQUES, BATON_PARAMS, repo_saved_state(profile))


def saved_state() -> GraphState:
    return repo_saved_state(repos.current())


def table() -> IdTable:
    return repo_table(repos.current())


def snapshot(as_of: int) -> GraphState:
    return repo_snapshot(repos.current(), as_of)


def learner() -> Learner:
    return repo_learner(repos.current())


@cache
def graph_counts(database: str = "") -> dict:
    """HydraDB node and link counts for one repo's database, cached until the next learning step changes the graph."""
    return db.counts()


def resolve(entity: str) -> str | None:
    """The vocabulary name for a prefixed or bare entity name, trying kinds in prefix order."""
    names = table().entities
    if entity in names:
        return entity
    return next((prefix + entity for prefix in KINDS_BY_PREFIX if prefix + entity in names), None)


@per_repo
def route_issue(title: str, body: str, reporter: str = "", as_of: int | None = None) -> RouteResult:
    """Route an issue live through HydraDB, or score against the snapshot at `as_of` learning issues."""
    if as_of is None:
        result = route(title, body, reporter, table())
    else:
        result = route_state(snapshot(as_of), title, body, reporter, table()).result
    if not result.teams:
        result.message = f"nothing in this issue matches what Baton learned from {repos.current().repo}, so it cannot be routed"
    return result


@per_repo
def record_outcome(issue: Issue, team: str) -> dict:
    """Apply one learning step for an issue whose real team is now known; returns what changed."""
    if team not in table().teams:
        raise ValueError(f"unknown team {team!r}")
    with learn_lock:
        live = learner()
        if issue.number in live.state.history or issue.number in live.state.learned_order:
            return {"team": team, "issue": issue.number, "already_learned": True}
        outcome = live.learn(issue, [team])
        graph_counts.cache_clear()
        path = live_state_file(repos.current())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(live.state.to_json(), separators=(",", ":")) + "\n")
    keys = ("issue", "predicted", "correct", "links_reweighted", "shortcuts_created", "merges")
    return {"team": team, "already_learned": False, **{key: outcome[key] for key in keys}}


@per_repo
def curve() -> dict:
    """Return the repo's curve file: {"lines": {name: [{"issues": n, "top1": f, "top3": f}, ...]}}."""
    path = repos.current().curve_file
    if not path.exists():
        return {"lines": {}}
    return {"lines": json.loads(path.read_text())["lines"]}


@per_repo
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


@per_repo
def stats() -> dict:
    """Return node and link counts plus issues_learned, links_reweighted, merges, shortcuts, misroutes_avoided."""
    profile = repos.current()
    counts = graph_counts(profile.database)
    counters = learner().state.counters
    summary = json.loads(profile.curve_file.read_text()).get("meta", {}).get("summary", {}) if profile.curve_file.exists() else {}
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


@per_repo
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


@per_repo
def reporter_history(username: str) -> list[dict]:
    """Return teams that fixed this reporter's earlier issues: [{team, count}]."""
    name = f"user:{username.lower()}"
    counts = Counter({team: n for (entity, team), n in learner().state.history_paths.items() if entity == name})
    return [{"team": team, "count": count} for team, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


@per_repo
def team_profile(team: str, limit: int = 15) -> list[dict]:
    """Return the entities most strongly linked to a team: [{entity, kind, strength}]."""
    links = [(entity, link) for (entity, linked_team), link in learner().state.routes.items() if linked_team == team]
    ranked = sorted(links, key=lambda item: (-item[1].strength, item[0]))[:limit]
    return [{"entity": display_name(entity), "kind": kind_of(entity), "strength": round(link.strength, 3)} for entity, link in ranked]


def list_repos() -> list[dict]:
    """Every repo Baton can route for: [{repo, signal, prefix, owners, issues_learned, snapshots, test_top1}], Kubernetes first."""
    found = []
    for name in repos.loaded():
        profile = repos.load(name)
        curve_lines = json.loads(profile.curve_file.read_text())["lines"] if profile.curve_file.exists() else {}
        found.append({
            "repo": profile.repo,
            "signal": profile.signal,
            "prefix": profile.prefix,
            "owners": len(repo_table(profile).teams),
            "issues_learned": repo_saved_state(profile).counters["issues_learned"],
            "snapshots": list(profile.sizes.snapshots),
            "test_top1": curve_lines.get("baton", [{}])[-1].get("top1"),
        })
    return found
