"""Deterministic stand-in for baton.service, used when BATON_FAKE_SERVICE=1."""

import math
import re
import zlib
from functools import wraps

from baton.config import ENTITY_ID_BASE, ISSUE_ID_BASE, LEARNING_SIZE, TEAM_ID_BASE
from baton.models import Issue, RouteResult, TeamScore
from baton.repos import KUBERNETES_PROFILE

TEAMS = ["sig/node", "sig/network", "sig/storage", "sig/api-machinery", "sig/scheduling", "sig/cli", "sig/auth"]

ENTITIES: dict[str, dict] = {
    "kubelet": {"kind": "component", "early": {"sig/node": 1.2, "sig/storage": 0.6, "sig/network": 0.3}, "late": {"sig/node": 3.4, "sig/storage": 0.5}},
    "oom": {"kind": "word", "early": {"sig/node": 0.5, "sig/scheduling": 0.4}, "late": {"sig/node": 2.6}, "shortcut": True},
    "cgroup": {"kind": "word", "early": {"sig/node": 0.4}, "late": {"sig/node": 2.1}, "shortcut": True},
    "pkg/kubelet/cm": {"kind": "path", "early": {"sig/node": 0.6}, "late": {"sig/node": 2.8}},
    "kube-proxy": {"kind": "component", "early": {"sig/network": 1.0}, "late": {"sig/network": 3.1}},
    "iptables": {"kind": "word", "early": {"sig/network": 0.5, "sig/node": 0.3}, "late": {"sig/network": 2.4}, "shortcut": True},
    "service": {"kind": "word", "early": {"sig/network": 0.4, "sig/api-machinery": 0.4}, "late": {"sig/network": 1.2, "sig/api-machinery": 0.6}},
    "apiserver": {"kind": "component", "early": {"sig/api-machinery": 1.0}, "late": {"sig/api-machinery": 3.2}},
    "etcd": {"kind": "component", "early": {"sig/api-machinery": 0.9}, "late": {"sig/api-machinery": 2.5}},
    "watch": {"kind": "word", "early": {"sig/api-machinery": 0.3, "sig/node": 0.3}, "late": {"sig/api-machinery": 1.4}},
    "csi": {"kind": "component", "early": {}, "late": {"sig/storage": 3.0}, "first_seen": 500},
    "volume": {"kind": "word", "early": {"sig/node": 0.9, "sig/storage": 0.4}, "late": {"sig/storage": 2.3, "sig/node": 0.2}},
    "persistentvolumeclaim": {"kind": "word", "early": {"sig/storage": 0.5}, "late": {"sig/storage": 2.0}},
    "scheduler": {"kind": "component", "early": {"sig/scheduling": 1.0}, "late": {"sig/scheduling": 3.0}},
    "preemption": {"kind": "word", "early": {"sig/scheduling": 0.3, "sig/node": 0.4}, "late": {"sig/scheduling": 2.2}},
    "kubectl": {"kind": "component", "early": {"sig/cli": 1.0}, "late": {"sig/cli": 3.0}},
    "rbac": {"kind": "word", "early": {"sig/auth": 0.6, "sig/api-machinery": 0.5}, "late": {"sig/auth": 2.7}},
    "timeout": {"kind": "word", "early": {"sig/node": 0.4, "sig/network": 0.4, "sig/api-machinery": 0.4}, "late": {"sig/network": 0.7, "sig/node": 0.6, "sig/api-machinery": 0.6}},
    "context deadline exceeded": {"kind": "error", "early": {"sig/api-machinery": 0.4, "sig/node": 0.5}, "late": {"sig/api-machinery": 0.9, "sig/node": 0.8}},
    "dims": {"kind": "reporter", "early": {"sig/node": 0.3, "sig/cli": 0.3}, "late": {"sig/node": 0.6, "sig/cli": 0.5}},
}

ALIASES = {"kube-apiserver": "apiserver", "pvc": "persistentvolumeclaim"}
SPLITS = {("timeout", "kubelet"): {"name": "timeout + kubelet", "late": {"sig/node": 2.4}}}
DEMO_STAGES = (0, 500, 1000, LEARNING_SIZE)
MERGE_STAGE = 1000
SPLIT_STAGE = 1000
STOPWORDS = {"when", "with", "from", "that", "this", "after", "before", "into", "does", "doesn't", "should", "while", "about", "there", "their", "using", "fails", "failed", "error", "issue", "after", "being", "have", "will", "when", "pods", "pod"}
TOKEN = re.compile(r"[a-z0-9][a-z0-9_./+-]*")

STATS = {
    "nodes": 3412,
    "links": 18760,
    "teams": 23,
    "entities": 1689,
    "issues": 1700,
    "issues_learned": 1700,
    "links_reweighted": 9431,
    "merges": 37,
    "shortcuts": 212,
    "misroutes_avoided": 186,
}


def demo_repo_only(function):
    """Accept a `repo` keyword like the real service, serving only the Kubernetes demo."""

    @wraps(function)
    def call(*args, repo: str | None = None, **kwargs):
        if repo not in (None, "", KUBERNETES_PROFILE.repo):
            raise LookupError(f"unknown repo {repo}; the demo service routes for {KUBERNETES_PROFILE.repo} only")
        return function(*args, **kwargs)

    return call


def _history_issue(entity: str, team: str, n: int = 0) -> int:
    """Return a stable fake past-issue number for an entity and team."""
    return 100_000 + zlib.crc32(f"{entity}|{team}|{n}".encode()) % 25_000


def _tokens(text: str) -> list[str]:
    """Lowercased tokens with trailing punctuation removed."""
    return [t.rstrip(".,:;/-") for t in TOKEN.findall(text.lower())]


def _matches(name: str, text: str, tokens: set[str]) -> bool:
    """True when an entity name appears in the text."""
    if " " in name:
        return name in text
    return name in tokens or any(t.startswith(name + "/") for t in tokens)


def _strengths(entity: dict, stage: int) -> dict[str, float]:
    """Interpolate an entity's team strengths at a learning stage."""
    if stage < entity.get("first_seen", 0):
        return {}
    t = stage / LEARNING_SIZE
    teams = set(entity["early"]) | set(entity["late"])
    return {team: entity["early"].get(team, 0) * (1 - t) + entity["late"].get(team, 0) * t for team in teams}


@demo_repo_only
def route_issue(title: str, body: str, reporter: str = "", as_of: int | None = None) -> RouteResult:
    """Score teams from a fixed entity table, interpolated by learning stage."""
    if as_of not in (None, *DEMO_STAGES):
        raise ValueError(f"as_of must be one of {list(DEMO_STAGES)} for {KUBERNETES_PROFILE.repo}")
    stage = LEARNING_SIZE if as_of is None else as_of
    text = f"{title}\n{body}".lower()
    tokens = set(_tokens(text))
    if reporter:
        tokens.add(reporter.lower())

    hits: list[tuple[str, list[str], dict[str, float]]] = []
    for name, entity in ENTITIES.items():
        if _matches(name, text, tokens):
            hits.append((name, [name], _strengths(entity, stage)))
    for alias, canonical in ALIASES.items():
        if stage >= MERGE_STAGE and _matches(alias, text, tokens):
            hits.append((alias, [alias, canonical], _strengths(ENTITIES[canonical], stage)))
    for (a, b), split in SPLITS.items():
        if stage >= SPLIT_STAGE and _matches(a, text, tokens) and _matches(b, text, tokens):
            t = stage / LEARNING_SIZE
            hits.append((split["name"], [split["name"]], {team: s * t for team, s in split["late"].items()}))

    hits = [h for h in hits if h[2]]
    scores: dict[str, float] = {}
    best: dict[str, tuple[float, list[str]]] = {}
    for name, prefix, strengths in hits:
        for team, strength in strengths.items():
            if strength <= 0:
                continue
            scores[team] = scores.get(team, 0) + strength
            if strength > best.get(team, (0, []))[0]:
                via = [f"#{_history_issue(name, team)}"] if stage == 0 else []
                best[team] = (strength, prefix + via + [team])

    matched = {n for h in hits for n in h[1]}
    unknown = {t for t in _tokens(title) if len(t) >= 4 and t not in STOPWORDS and t not in matched and t not in ENTITIES}
    total = sum(scores.values())
    ranked = sorted(scores, key=lambda team: (-scores[team], team))[:3]
    teams = [TeamScore(team=team, share=round(scores[team] / total, 3), path=best[team][1]) for team in ranked]
    return RouteResult(
        teams=teams,
        confidence=teams[0].share if teams else 0.0,
        entities_found=len(hits),
        entities_unknown=len(unknown),
    )


@demo_repo_only
def record_outcome(issue: Issue, team: str) -> dict:
    """Report what one learning step would change, without mutating anything."""
    result = route_issue(issue.title, issue.body, issue.reporter)
    return {
        "issue": issue.number,
        "team": team,
        "predicted": result.top_team,
        "correct": result.top_team == team,
        "links_reweighted": result.entities_found,
        "shortcuts_created": 0,
        "merges": 0,
    }


def _saturate(n: int, gain: float, scale: float) -> float:
    """Rise from 0 towards gain with a time constant of scale issues."""
    return gain * (1 - math.exp(-n / scale))


def _wobble(n: int, phase: float) -> float:
    """Small deterministic noise that is zero at issue 0."""
    return 0.006 * math.sin(n / 137 + phase) * (1 - math.exp(-n / 300))


@demo_repo_only
def curve() -> dict:
    """Return 18 points per line for frozen, count_only, baton and each technique."""
    points = range(0, LEARNING_SIZE + 1, 100)
    base = 0.30
    count_only = {n: base + _saturate(n, 0.22, 600) for n in points}
    gains = {
        "baton": (0.41, 500),
        "reweight": (0.11, 700),
        "shortcuts": (0.05, 700),
        "merging": (0.03, 900),
        "splitting": (0.02, 900),
        "gap_filling": (0.06, 300),
    }

    def point(n: int, top1: float, lift_at: int | None = None) -> dict:
        top3 = min(0.95, top1 + 0.18 + _saturate(n if lift_at is None else lift_at, 0.03, 800))
        return {"issues": n, "top1": round(top1, 3), "top3": round(top3, 3)}

    lines = {
        "frozen": [point(n, count_only[min(n, 200)], min(n, 200)) for n in points],
        "count_only": [point(n, count_only[n] + _wobble(n, 0.0)) for n in points],
        "baton": [point(n, base + _saturate(n, *gains["baton"]) + _wobble(n, 1.3)) for n in points],
    }
    for i, name in enumerate(["reweight", "shortcuts", "merging", "splitting", "gap_filling"]):
        gain, scale = gains[name]
        lines[name] = [point(n, count_only[n] + _saturate(n, gain, scale) + _wobble(n, 2.0 + i)) for n in points]
    return {"lines": lines}


def _build_graph() -> tuple[dict[str, dict], list[dict]]:
    """Build the live fake graph: nodes by name and directed links."""
    nodes: dict[str, dict] = {}

    def add(name: str, label: str, kind: str | None, node_id: int) -> None:
        nodes.setdefault(name, {"id": node_id, "name": name, "label": label, "kind": kind})

    for i, team in enumerate(TEAMS):
        add(team, "Team", None, TEAM_ID_BASE + i)
    entity_names = list(ENTITIES) + list(ALIASES) + [s["name"] for s in SPLITS.values()]
    for i, name in enumerate(entity_names):
        kind = ENTITIES[name]["kind"] if name in ENTITIES else ENTITIES[ALIASES[name]]["kind"] if name in ALIASES else "word"
        add(name, "Entity", kind, ENTITY_ID_BASE + i)

    links: list[dict] = []

    def link(source: str, target: str, kind: str, strength: float, shortcut: bool = False) -> None:
        links.append({"source": nodes[source]["id"], "target": nodes[target]["id"], "type": kind, "strength": round(strength, 2), "shortcut": shortcut})

    for name, entity in ENTITIES.items():
        for team, strength in entity["late"].items():
            link(name, team, "ROUTES_TO", strength, shortcut=bool(entity.get("shortcut")) and strength == max(entity["late"].values()))
        for team in entity["late"]:
            for n in range(2):
                number = _history_issue(name, team, n)
                issue_name = f"#{number}"
                add(issue_name, "Issue", None, ISSUE_ID_BASE + number)
                link(name, issue_name, "SEEN_IN", 1.0)
                link(issue_name, team, "OWNED_BY", 1.0)
    for alias, canonical in ALIASES.items():
        link(alias, canonical, "SAME_AS", 10.0)
        link(canonical, alias, "SAME_AS", 10.0)
    for split in SPLITS.values():
        for team, strength in split["late"].items():
            link(split["name"], team, "ROUTES_TO", strength)
    return nodes, links


NODES, LINKS = _build_graph()
NODES_BY_ID = {node["id"]: node for node in NODES.values()}


@demo_repo_only
def graph_around(entity: str) -> dict:
    """Return the entity, its links, merged names, history issues and the strongest peers per team."""
    focus = NODES.get(entity.lower())
    if focus is None or focus["label"] != "Entity":
        return {"nodes": [], "links": []}

    chosen: list[dict] = [link for link in LINKS if focus["id"] in (link["source"], link["target"])]
    hop = {link["target"] for link in chosen} | {link["source"] for link in chosen}
    for node_id in hop - {focus["id"]}:
        if NODES_BY_ID[node_id]["label"] != "Team":
            chosen += [link for link in LINKS if link["source"] == node_id and link not in chosen]
    teams = {link["target"] for link in chosen if NODES_BY_ID[link["target"]]["label"] == "Team"}
    for team_id in teams:
        peers = sorted(
            (link for link in LINKS if link["target"] == team_id and link["type"] == "ROUTES_TO" and link not in chosen),
            key=lambda link: -link["strength"],
        )
        chosen += peers[:2]

    ids = {focus["id"]} | {link["source"] for link in chosen} | {link["target"] for link in chosen}
    return {"nodes": [NODES_BY_ID[i] for i in sorted(ids)], "links": chosen}


@demo_repo_only
def stats() -> dict:
    """Return fixed demo counters."""
    return dict(STATS)


@demo_repo_only
def similar_past_issues(title: str, body: str, limit: int = 5) -> list[dict]:
    """Return fake past issues for the entities found in the text."""
    result = route_issue(title, body)
    rows = [
        {"number": _history_issue(team.path[0], team.team), "title": f"{team.path[0]} regression", "team": team.team, "shared": [team.path[0]]}
        for team in result.teams
    ]
    return rows[:limit]


@demo_repo_only
def reporter_history(username: str) -> list[dict]:
    """Return teams that fixed this reporter's earlier issues."""
    entity = ENTITIES.get(username.lower())
    if entity is None or entity["kind"] != "reporter":
        return []
    return [{"team": team, "count": round(strength * 4)} for team, strength in sorted(entity["late"].items(), key=lambda kv: -kv[1])]


@demo_repo_only
def team_profile(team: str, limit: int = 15) -> list[dict]:
    """Return the entities most strongly linked to a team."""
    rows = [{"entity": name, "kind": e["kind"], "strength": e["late"][team]} for name, e in ENTITIES.items() if team in e["late"]]
    return sorted(rows, key=lambda row: -row["strength"])[:limit]


def list_repos() -> list[dict]:
    """The one demo repo."""
    return [{"repo": KUBERNETES_PROFILE.repo, "signal": "label_prefix", "prefix": "sig/", "owners": len(TEAMS), "issues_learned": LEARNING_SIZE, "snapshots": list(DEMO_STAGES), "test_top1": None}]
