"""Rewrite HydraDB from a saved snapshot (default: the baton end state at 1,700 issues) in seconds, instead of re-running the curve."""

import argparse
import json

from baton import db, snapshots
from baton.config import SNAPSHOT_POINTS
from baton.ids import IdTable
from baton.ingest import setup_graph
from baton.service import LIVE_STATE_FILE
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


def restore(as_of: int) -> dict:
    """Wipe the graph, write the snapshot taken after `as_of` learning issues, drop the live state file, return db counts."""
    state = snapshots.load(as_of)
    table = snapshot_table(state)
    issues, routes, same_as = graph_rows(state, table)
    setup_graph(table)
    db.upsert_issues(issues)
    db.upsert_routes(routes)
    db.upsert_same_as(same_as)
    LIVE_STATE_FILE.unlink(missing_ok=True)
    return db.counts()


def main() -> None:
    """Restore the graph and print its counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=int, choices=SNAPSHOT_POINTS, default=SNAPSHOT_POINTS[-1])
    print(json.dumps(restore(parser.parse_args().as_of)))


if __name__ == "__main__":
    main()
