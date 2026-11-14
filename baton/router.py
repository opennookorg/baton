"""Route an issue: its known entities, one weighted algo.MSpaths call to every team, teams scored by 1 / pathWeight, discounted for generic entities."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from baton import db
from baton.config import HISTORY_COST, SAME_AS_COST
from baton.entities import extract
from baton.ids import IdTable
from baton.models import RouteResult, TeamScore
from baton.passes import with_compounds
from baton.snapshots import GraphState

MAX_LEN = 3
PATH_COUNT = 3
TOP_TEAMS = 3
MIN_WEIGHT = 1e-9


@dataclass
class Routed:
    """A RouteResult plus the raw paths (kind-prefixed entity names) it was scored from."""

    result: RouteResult
    paths: list[dict]


def display_name(node: str) -> str:
    """A path node as shown in API output: entity names lose their kind prefix; teams and #issues stay."""
    return node.split(":", 1)[1] if ":" in node else node


def known_entities(title: str, body: str, reporter: str, table: IdTable) -> tuple[list[str], int]:
    """Return (entity names in the graph vocabulary, plus split compounds present, and the count of extracted entities that are not)."""
    names = [entity.name for entity in extract(title, body, reporter)]
    known = [name for name in names if table.entity_id(name) is not None]
    return with_compounds(known, table.entities), len(names) - len(known)


def cheapest_per_pair(paths: Iterable[dict], path_count: int = PATH_COUNT, exclude_issue: int | None = None) -> list[dict]:
    """Keep the `path_count` cheapest paths per (source, team) pair, as algo.MSpaths does, skipping one issue."""
    skip = None if exclude_issue is None else f"#{exclude_issue}"
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in paths:
        if skip not in path["nodes"]:
            by_pair[(path["nodes"][0], path["nodes"][-1])].append(path)
    return [
        path
        for pair in sorted(by_pair)
        for path in sorted(by_pair[pair], key=lambda p: (p["weight"], p["nodes"]))[:path_count]
    ]


def rank(paths: list[dict], found: int, unknown: int, top: int = TOP_TEAMS) -> Routed:
    """Score each team by the sum of 1 / pathWeight over its paths, each source entity's part divided by how many teams it reaches."""
    scores: dict[str, float] = defaultdict(float)
    teams_reached: dict[str, set[str]] = defaultdict(set)
    best: dict[str, dict] = {}
    for path in paths:
        teams_reached[path["nodes"][0]].add(path["nodes"][-1])
    for path in paths:
        team = path["nodes"][-1]
        scores[team] += 1.0 / max(path["weight"], MIN_WEIGHT) / len(teams_reached[path["nodes"][0]])
        if team not in best or (path["weight"], path["nodes"]) < (best[team]["weight"], best[team]["nodes"]):
            best[team] = path
    total = sum(scores.values())
    ranked = sorted(scores, key=lambda team: (-scores[team], team))[:top]
    teams = [TeamScore(team, round(scores[team] / total, 3), [display_name(n) for n in best[team]["nodes"]]) for team in ranked]
    result = RouteResult(teams=teams, confidence=teams[0].share if teams else 0.0, entities_found=found, entities_unknown=unknown)
    return Routed(result, paths)


def route_live(title: str, body: str, reporter: str, table: IdTable, exclude_issue: int | None = None) -> Routed:
    """Route through HydraDB with one weighted algo.MSpaths call from the known entities to every team."""
    known, unknown = known_entities(title, body, reporter, table)
    teams = sorted(table.teams)
    path_count = PATH_COUNT + (exclude_issue is not None)
    limit = max(500, len(known) * len(teams) * path_count)
    paths = db.ms_paths(known, teams, MAX_LEN, path_count, limit)
    return rank(cheapest_per_pair(paths, PATH_COUNT, exclude_issue), len(known), unknown)


def route(title: str, body: str, reporter: str, table: IdTable, exclude_issue: int | None = None) -> RouteResult:
    """Route an issue live through HydraDB."""
    return route_live(title, body, reporter, table, exclude_issue).result


def state_paths(state: GraphState, sources: Iterable[str], teams: set[str], max_len: int = MAX_LEN) -> list[dict]:
    """Every simple outgoing path of at most `max_len` links from the sources to the teams, in a GraphState."""
    found: list[dict] = []

    def walk(entity: str, nodes: list[str], rels: list[str], weight: float) -> None:
        depth = len(rels)
        if depth >= max_len:
            return
        for team, link in state.routes_out.get(entity, {}).items():
            if team in teams:
                found.append({"nodes": nodes + [team], "rels": rels + ["ROUTES_TO"], "weight": weight + link.cost})
        if depth + 2 <= max_len:
            for number in state.seen_in.get(entity, ()):
                for team in state.history[number].teams:
                    if team in teams:
                        found.append(
                            {
                                "nodes": nodes + [f"#{number}", team],
                                "rels": rels + ["SEEN_IN", "OWNED_BY"],
                                "weight": weight + 2 * HISTORY_COST,
                            }
                        )
        for other in state.same_as_out.get(entity, ()):
            if other not in nodes:
                walk(other, nodes + [other], rels + ["SAME_AS"], weight + SAME_AS_COST)

    for source in dict.fromkeys(sources):
        walk(source, [source], [], 0.0)
    return found


def route_state(
    state: GraphState, title: str, body: str, reporter: str, table: IdTable, exclude_issue: int | None = None
) -> Routed:
    """Route in pure Python against a GraphState (a snapshot), with the same scoring as the live router."""
    known, unknown = known_entities(title, body, reporter, table)
    paths = state_paths(state, known, set(table.teams))
    return rank(cheapest_per_pair(paths, PATH_COUNT, exclude_issue), len(known), unknown)
