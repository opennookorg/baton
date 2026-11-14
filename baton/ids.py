"""Stable name-to-ID table for HydraDB nodes: teams, entities and issues."""

import json
from collections.abc import Iterable
from pathlib import Path

from baton.config import ENTITY_ID_BASE, ENTITY_TABLE_FILE, ISSUE_ID_BASE, MIN_ENTITY_ISSUES, TEAM_ID_BASE, TEAM_ID_MAX
from baton.dataset import load_issues, load_reserve, split
from baton.entities import build_vocabulary


class IdTable:
    """Maps team and entity names to integer node IDs; issues map to ISSUE_ID_BASE + number."""

    def __init__(self, teams: dict[str, int] | None = None, entities: dict[str, int] | None = None):
        self.teams: dict[str, int] = dict(teams or {})
        self.entities: dict[str, int] = dict(entities or {})
        self.names_by_id: dict[int, str] = {i: n for n, i in self.teams.items()} | {i: n for n, i in self.entities.items()}
        self.next_team_id = max(self.teams.values(), default=TEAM_ID_BASE - 1) + 1
        self.next_entity_id = max(self.entities.values(), default=ENTITY_ID_BASE - 1) + 1

    def add_team(self, name: str) -> int:
        """Return the team's ID, assigning the next free one if it is new."""
        if name not in self.teams:
            if self.next_team_id > TEAM_ID_MAX:
                raise ValueError(f"team ID range exhausted at {name!r}")
            self.teams[name] = self.next_team_id
            self.names_by_id[self.next_team_id] = name
            self.next_team_id += 1
        return self.teams[name]

    def add_entity(self, name: str) -> int:
        """Return the entity's ID, assigning the next free one if it is new."""
        if name not in self.entities:
            if self.next_entity_id >= ISSUE_ID_BASE:
                raise ValueError(f"entity ID range exhausted at {name!r}")
            self.entities[name] = self.next_entity_id
            self.names_by_id[self.next_entity_id] = name
            self.next_entity_id += 1
        return self.entities[name]

    def team_id(self, name: str) -> int:
        """The ID of a known team; raises KeyError when unknown."""
        return self.teams[name]

    def entity_id(self, name: str) -> int | None:
        """The ID of a known entity, or None when it is not in the table."""
        return self.entities.get(name)

    @staticmethod
    def issue_id(number: int) -> int:
        """The node ID of a GitHub issue number."""
        return ISSUE_ID_BASE + number

    def name_of(self, node_id: int) -> str:
        """The team or entity name for a node ID, or `#<number>` for an issue."""
        if node_id >= ISSUE_ID_BASE:
            return f"#{node_id - ISSUE_ID_BASE}"
        return self.names_by_id[node_id]

    def save(self, path: Path = ENTITY_TABLE_FILE) -> None:
        """Write the table as JSON."""
        path.write_text(json.dumps({"teams": self.teams, "entities": self.entities}, indent=1, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path = ENTITY_TABLE_FILE) -> "IdTable":
        """Read a table saved with `save`."""
        payload = json.loads(path.read_text())
        return cls(payload["teams"], payload["entities"])


def build_table(sigs: Iterable[str], entity_names: Iterable[str]) -> IdTable:
    """Build a table assigning IDs in sorted name order, so the same inputs always give the same IDs."""
    table = IdTable()
    for team in sorted(set(sigs)):
        table.add_team(team)
    for name in sorted(set(entity_names)):
        table.add_entity(name)
    return table


def build_default() -> IdTable:
    """Build the table from every sig label in issues and reserve plus the learning-stream vocabulary."""
    issues, reserve = load_issues(), load_reserve()
    learning, _ = split(issues)
    sigs = {sig for issue in issues + reserve for sig in issue.sigs}
    return build_table(sigs, build_vocabulary(learning, MIN_ENTITY_ISSUES))


if __name__ == "__main__":
    table = build_default()
    table.save()
    print(f"saved {len(table.teams)} teams and {len(table.entities)} entities to {ENTITY_TABLE_FILE}")
