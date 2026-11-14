"""The learning loop: route, reveal, write the issue, reweight; every BATCH_SIZE issues add shortcuts and prune history."""

from dataclasses import dataclass, fields

from baton import db
from baton.config import BATCH_SIZE, LearnParams, Techniques
from baton.ids import IdTable
from baton.ingest import issue_entities, issue_row, issue_teams
from baton.models import Issue
from baton.router import Routed, route_live, route_state
from baton.snapshots import GraphState, Link, Pair, PastIssue

IMPLEMENTED_TECHNIQUES = ("reweight", "shortcuts")
SHORTCUT_SCALE = 2.0


def check_techniques(techniques: Techniques) -> None:
    """Refuse switches whose passes do not exist yet, so no line claims a technique it did not run."""
    missing = [f.name for f in fields(techniques) if getattr(techniques, f.name) and f.name not in IMPLEMENTED_TECHNIQUES]
    if missing:
        raise ValueError(f"techniques not implemented yet: {', '.join(missing)}")


def winning_pairs(routed: Routed, team: str | None) -> set[Pair]:
    """The ROUTES_TO links on the paths that reached the predicted team."""
    return {
        (path["nodes"][k], path["nodes"][k + 1])
        for path in routed.paths
        if path["nodes"][-1] == team
        for k, rel in enumerate(path["rels"])
        if rel == "ROUTES_TO"
    }


def reweight(
    links: dict[Pair, Link], entities: list[str], teams: list[str], predicted: str | None, winning: set[Pair], params: LearnParams
) -> dict[Pair, Link]:
    """Right: reward the winning links. Wrong: shrink links to the wrong team, reward or create links to the real teams."""
    if predicted in teams:
        return {
            pair: Link(links[pair].strength + params.reward, links[pair].hits + 1, links[pair].misses, links[pair].shortcut)
            for pair in winning
            if pair in links
        }
    changed: dict[Pair, Link] = {}
    for entity in entities:
        link = links.get((entity, predicted))
        if link is not None:
            changed[(entity, predicted)] = Link(max(params.floor, link.strength * params.penalty), link.hits, link.misses + 1, link.shortcut)
        for team in teams:
            link = links.get((entity, team)) or Link(0.0)
            changed[(entity, team)] = Link(link.strength + params.reward, link.hits + 1, link.misses, link.shortcut)
    return changed


def shortcut_strength(pair: Pair, paths: int, state: GraphState) -> float:
    """Shortcut strength: SHORTCUT_SCALE x the share of the entity's history issues the team owns (raw counts let generic entities drown the rest)."""
    return SHORTCUT_SCALE * paths / max(state.entity_issues[pair[0]], 1)


def shortcut_pass(state: GraphState, params: LearnParams) -> tuple[dict[Pair, Link], dict[Pair, float]]:
    """Give every entity reaching a team through enough history paths a direct link, replacing its previous shortcut part."""
    changed: dict[Pair, Link] = {}
    absorbed: dict[Pair, float] = {}
    for pair, paths in state.history_paths.items():
        if paths < params.shortcut_min_paths:
            continue
        new, old = shortcut_strength(pair, paths, state), state.absorbed.get(pair, 0.0)
        link = state.routes.get(pair)
        if new == old and link is not None and link.shortcut:
            continue
        base = link or Link(0.0)
        changed[pair] = Link(max(params.floor, base.strength + new - old), base.hits, base.misses, True)
        absorbed[pair] = new
    return changed, absorbed


def prunable(state: GraphState, keep: int) -> list[int]:
    """History issues older than the last `keep` learned whose every entity-team pair already has a ROUTES_TO link."""
    old = state.learned_order[:-keep] if keep else state.learned_order
    return [
        number
        for number in old
        if number in state.history
        and all((e, t) in state.routes for e in state.history[number].entities for t in state.history[number].teams)
    ]


@dataclass
class Learner:
    """Runs the learning loop on HydraDB (live) or on the in-memory mirror only (offline, for tuning on the stream)."""

    table: IdTable
    techniques: Techniques
    params: LearnParams = LearnParams()
    state: GraphState | None = None
    live: bool = True

    def __post_init__(self) -> None:
        check_techniques(self.techniques)
        self.state = self.state or GraphState()

    def route(self, issue: Issue) -> Routed:
        """Route an issue against the current graph."""
        if self.live:
            return route_live(issue.title, issue.body, issue.reporter, self.table, issue.number)
        return route_state(self.state, issue.title, issue.body, issue.reporter, self.table, issue.number)

    def learn(self, issue: Issue, teams: list[str] | None = None) -> dict:
        """Route, reveal the real teams, write the issue as history, reweight; run batch passes every BATCH_SIZE."""
        routed = self.route(issue)
        predicted = routed.result.top_team
        teams = sorted(set(teams)) if teams else issue_teams(issue, self.table)
        entities = issue_entities(issue, self.table)
        self.write_history(issue, entities, teams)
        changed: dict[Pair, Link] = {}
        if self.techniques.reweight and teams:
            winning = winning_pairs(routed, predicted)
            links = self.read_links(set(entities) | {e for e, _ in winning})
            changed = reweight(links, entities, teams, predicted, winning, self.params)
            self.write_links(changed)
        counters = self.state.counters
        counters["issues_learned"] += 1
        counters["links_reweighted"] += len(changed)
        counters["misroutes"] += predicted not in teams
        batch = self.end_batch() if counters["issues_learned"] % BATCH_SIZE == 0 else {}
        return {
            "issue": issue.number,
            "team": teams[0] if len(teams) == 1 else teams,
            "predicted": predicted,
            "correct": predicted in teams,
            "confidence": routed.result.confidence,
            "links_reweighted": len(changed),
            "shortcuts_created": batch.get("shortcuts_created", 0),
            "merges": 0,
        }

    def write_history(self, issue: Issue, entities: list[str], teams: list[str]) -> None:
        """Write the Issue node, SEEN_IN from each known entity and OWNED_BY to every real team."""
        if self.live:
            db.upsert_issues([issue_row(issue, self.table, entities, teams)])
        state = self.state
        if issue.number in state.history:
            state.remove_issue(issue.number)
        state.add_issue(issue.number, PastIssue(issue.title, entities, teams))
        state.learned_order.append(issue.number)
        for entity in entities:
            state.entity_issues[entity] += 1
            for team in teams:
                state.history_paths[(entity, team)] += 1

    def read_links(self, entities: set[str]) -> dict[Pair, Link]:
        """Read the ROUTES_TO links leaving these entities (from HydraDB when live)."""
        if not self.live:
            return {(e, t): link for e in entities for t, link in self.state.routes_out.get(e, {}).items()}
        rows = db.routes_from_entities(self.table.entity_id(e) for e in sorted(entities))
        names = self.table.names_by_id
        return {
            (names[r["entity"]], names[r["team"]]): Link(r["strength"], r["hits"], r["misses"], bool(r["shortcut"])) for r in rows
        }

    def write_links(self, changed: dict[Pair, Link]) -> None:
        """Write changed ROUTES_TO links in one UNWIND batch and mirror them."""
        if not changed:
            return
        if self.live:
            db.upsert_routes(
                {
                    "entity": self.table.entity_id(e),
                    "team": self.table.team_id(t),
                    "strength": link.strength,
                    "cost": link.cost,
                    "hits": link.hits,
                    "misses": link.misses,
                    "shortcut": link.shortcut,
                }
                for (e, t), link in changed.items()
            )
        for pair, link in changed.items():
            self.state.set_link(pair, link)

    def end_batch(self) -> dict:
        """Run the shortcut pass and prune history covered by shortcuts; return what changed."""
        if not self.techniques.shortcuts:
            return {}
        changed, absorbed = shortcut_pass(self.state, self.params)
        created = sum(1 for pair in changed if not (pair in self.state.routes and self.state.routes[pair].shortcut))
        self.write_links(changed)
        self.state.absorbed.update(absorbed)
        self.state.counters["shortcuts"] += created
        pruned = prunable(self.state, self.params.history_keep)
        if self.live and pruned:
            db.delete_issues(self.table.issue_id(n) for n in pruned)
        for number in pruned:
            self.state.remove_issue(number)
        self.state.counters["issues_pruned"] += len(pruned)
        return {"shortcuts_created": created, "issues_pruned": len(pruned)}
