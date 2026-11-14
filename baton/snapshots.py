"""In-memory mirror of the learned graph, saved as snapshots so "as of issue N" needs no HydraDB history."""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from baton.config import SNAPSHOT_DIR

Pair = tuple[str, str]
COUNTER_NAMES = ("issues_learned", "links_reweighted", "shortcuts", "misroutes", "merges", "issues_pruned", "splits", "gap_issues")


@dataclass
class Link:
    """One ROUTES_TO link as Python data; cost is always 1 / strength."""

    strength: float
    hits: int = 0
    misses: int = 0
    shortcut: bool = False

    @property
    def cost(self) -> float:
        """Path-search weight of the link."""
        return 1.0 / self.strength


@dataclass
class PastIssue:
    """A history issue in the graph: its known entities and the teams that own it."""

    title: str
    entities: list[str]
    teams: list[str]


@dataclass
class GraphState:
    """Every ROUTES_TO link, history issue and SAME_AS pair, entities added while learning, plus the learner's running totals."""

    routes: dict[Pair, Link] = field(default_factory=dict)
    history: dict[int, PastIssue] = field(default_factory=dict)
    same_as: set[Pair] = field(default_factory=set)
    history_paths: dict[Pair, int] = field(default_factory=lambda: defaultdict(int))
    absorbed: dict[Pair, float] = field(default_factory=dict)
    entity_issues: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    entity_misses: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    added_entities: list[str] = field(default_factory=list)
    learned_order: list[int] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNTER_NAMES, 0))

    routes_out: dict[str, dict[str, Link]] = field(default_factory=lambda: defaultdict(dict))
    seen_in: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    same_as_out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def set_link(self, pair: Pair, link: Link) -> None:
        """Add or replace one ROUTES_TO link."""
        self.routes[pair] = link
        self.routes_out[pair[0]][pair[1]] = link

    def add_issue(self, number: int, issue: PastIssue) -> None:
        """Add one history issue and its SEEN_IN and OWNED_BY links."""
        self.history[number] = issue
        for entity in issue.entities:
            self.seen_in[entity].add(number)

    def remove_issue(self, number: int) -> None:
        """Delete one history issue and its links."""
        for entity in self.history.pop(number).entities:
            self.seen_in[entity].discard(number)

    def add_same_as(self, a: str, b: str) -> None:
        """Add SAME_AS both ways."""
        self.same_as |= {(a, b), (b, a)}
        self.same_as_out[a].add(b)
        self.same_as_out[b].add(a)

    def to_json(self) -> dict:
        """Serialise to plain JSON data."""
        return {
            "routes": [[e, t, link.strength, link.hits, link.misses, link.shortcut] for (e, t), link in sorted(self.routes.items())],
            "history": {str(n): [i.title, i.entities, i.teams] for n, i in sorted(self.history.items())},
            "same_as": sorted([a, b] for a, b in self.same_as),
            "history_paths": [[e, t, n] for (e, t), n in sorted(self.history_paths.items())],
            "absorbed": [[e, t, n] for (e, t), n in sorted(self.absorbed.items())],
            "entity_issues": dict(sorted(self.entity_issues.items())),
            "entity_misses": dict(sorted(self.entity_misses.items())),
            "added_entities": self.added_entities,
            "learned_order": self.learned_order,
            "counters": self.counters,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "GraphState":
        """Rebuild a state saved with `to_json`."""
        state = cls()
        for e, t, strength, hits, misses, shortcut in payload["routes"]:
            state.set_link((e, t), Link(strength, hits, misses, shortcut))
        for number, (title, entities, teams) in payload["history"].items():
            state.add_issue(int(number), PastIssue(title, entities, teams))
        for a, b in payload["same_as"]:
            state.add_same_as(a, b)
        state.history_paths.update({(e, t): n for e, t, n in payload["history_paths"]})
        state.absorbed = {(e, t): n for e, t, n in payload["absorbed"]}
        state.entity_issues.update(payload["entity_issues"])
        state.entity_misses.update(payload.get("entity_misses", {}))
        state.added_entities = list(payload.get("added_entities", []))
        state.learned_order = list(payload["learned_order"])
        state.counters.update(payload["counters"])
        return state


def snapshot_path(as_of: int, directory: Path = SNAPSHOT_DIR) -> Path:
    """Where the snapshot taken after `as_of` learning issues lives."""
    return directory / f"{as_of}.json"


def save(state: GraphState, as_of: int, meta: dict | None = None, directory: Path = SNAPSHOT_DIR) -> Path:
    """Write a snapshot of the state after `as_of` learning issues."""
    directory.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(as_of, directory)
    path.write_text(json.dumps({"as_of": as_of, "meta": meta or {}, **state.to_json()}, separators=(",", ":")) + "\n")
    return path


def load(as_of: int, directory: Path = SNAPSHOT_DIR) -> GraphState:
    """Read the snapshot taken after `as_of` learning issues."""
    return GraphState.from_json(json.loads(snapshot_path(as_of, directory).read_text()))
