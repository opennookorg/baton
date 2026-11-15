"""Rewrite a repo's HydraDB graph from a saved snapshot (default: its final baton snapshot) in seconds, instead of re-running the curve."""

import argparse
import json

from baton import db, repos, snapshots
from baton.ids import IdTable
from baton.ingest import setup_graph
from baton.service import live_state_file
from baton.snapshots import GraphState


def snapshot_table(state: GraphState) -> IdTable:
    """The name-to-ID table plus the entities the learner added, replayed in order so IDs match the snapshot."""
    table = IdTable.load()
    for name in state.added_entities:
        table.add_entity(name)
    return table


def graph_rows(state: GraphState, table: IdTable) -> tuple[list[dict], list[dict], list[tuple[int, int]]]:
    """The db.upsert_issues rows, db.upsert_routes rows and SAME_AS id pairs that hold exactly this state."""
    issues = [
        {
            "id": table.issue_id(number),
            "number": number,
            "title": past.title,
            "teams": [table.team_id(team) for team in past.teams],
            "entities": [table.entity_id(name) for name in past.entities],
        }
        for number, past in sorted(state.history.items())
    ]
    routes = [
        {
            "entity": table.entity_id(entity),
            "team": table.team_id(team),
            "strength": link.strength,
            "cost": link.cost,
            "hits": link.hits,
            "misses": link.misses,
            "shortcut": link.shortcut,
        }
        for (entity, team), link in sorted(state.routes.items())
    ]
    same_as = [(table.entity_id(a), table.entity_id(b)) for a, b in sorted(state.same_as) if a < b]
    return issues, routes, same_as


def restore(as_of: int | None = None) -> dict:
    """Wipe the active repo's graph, write its snapshot after `as_of` learning issues (default: the last), drop its live state, return db counts."""
    profile = repos.current()
    as_of = profile.sizes.snapshots[-1] if as_of is None else as_of
    if as_of not in profile.sizes.snapshots:
        raise ValueError(f"as_of must be one of {list(profile.sizes.snapshots)} for {profile.repo}")
    state = snapshots.load(as_of)
    table = snapshot_table(state)
    issues, routes, same_as = graph_rows(state, table)
    setup_graph(table)
    db.upsert_issues(issues)
    db.upsert_routes(routes)
    db.upsert_same_as(same_as)
    live_state_file(profile).unlink(missing_ok=True)
    return db.counts()


def main() -> None:
    """Restore one repo's graph (Kubernetes by default) or every routable repo's with --all, and print the counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/name of an onboarded repo; Kubernetes by default")
    parser.add_argument("--all", action="store_true", help="restore every repo Baton routes for")
    parser.add_argument("--as-of", type=int, default=None, help="one of the repo's snapshot points; its last by default")
    args = parser.parse_args()
    for name in repos.loaded() if args.all else [args.repo]:
        with repos.use(repos.load(name)):
            print(json.dumps({"repo": repos.current().repo, **restore(args.as_of)}), flush=True)


if __name__ == "__main__":
    main()
