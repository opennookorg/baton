"""Load teams, the entity vocabulary and history issues into HydraDB; multi-sig issues get OWNED_BY to every sig."""

from collections.abc import Iterable

from baton import db, repos
from baton.dataset import split
from baton.entities import extract_issue, kind_of
from baton.ids import IdTable
from baton.models import Issue


def setup_graph(table: IdTable) -> None:
    """Wipe the graph and load every team and vocabulary entity, with no links."""
    db.reset()
    db.upsert_teams((team_id, name) for name, team_id in table.teams.items())
    db.upsert_entities((entity_id, name, kind_of(name)) for name, entity_id in table.entities.items())


def issue_teams(issue: Issue, table: IdTable) -> list[str]:
    """The issue's sig labels that are known teams, sorted."""
    return sorted(sig for sig in set(issue.sigs) if sig in table.teams)


def issue_entities(issue: Issue, table: IdTable) -> list[str]:
    """The issue's extracted entity names that are in the vocabulary."""
    return [entity.name for entity in extract_issue(issue) if table.entity_id(entity.name) is not None]


def issue_row(issue: Issue, table: IdTable, entities: list[str], teams: list[str]) -> dict:
    """The db.upsert_issues row for one history issue."""
    return {
        "id": table.issue_id(issue.number),
        "number": issue.number,
        "title": issue.title,
        "teams": [table.team_id(team) for team in teams],
        "entities": [table.entity_id(name) for name in entities],
    }


def ingest_history(issues: Iterable[Issue], table: IdTable) -> list[dict]:
    """Write issues as history (Issue node, SEEN_IN from each known entity, OWNED_BY to every sig); return the rows."""
    rows = [issue_row(i, table, issue_entities(i, table), issue_teams(i, table)) for i in issues]
    db.upsert_issues(rows)
    return rows


def expected_counts(rows: list[dict], table: IdTable) -> dict:
    """The node and link counts a graph holding exactly these history rows must have."""
    return {
        "nodes": {"Team": len(table.teams), "Entity": len(table.entities), "Issue": len(rows)},
        "links": {
            "ROUTES_TO": 0,
            "SEEN_IN": sum(len(set(row["entities"])) for row in rows),
            "OWNED_BY": sum(len(row["teams"]) for row in rows),
            "SAME_AS": 0,
        },
    }


def main() -> None:
    """Ingest the first frozen-size learning issues and check the graph counts match the data exactly."""
    table = IdTable.load()
    learning, _ = split()
    setup_graph(table)
    rows = ingest_history(learning[: repos.current().sizes.frozen], table)
    expected, actual = expected_counts(rows, table), db.counts()
    print(f"expected {expected}\nactual   {actual}")
    if expected != actual:
        raise SystemExit("graph counts do not match the data")
    print("counts match")


if __name__ == "__main__":
    main()
