"""Data shapes shared by every module, the API and the MCP server."""

from dataclasses import asdict, dataclass, field
from typing import Literal

EntityKind = Literal["component", "path", "word", "error", "reporter"]


@dataclass(frozen=True)
class Issue:
    """One closed GitHub issue, as stored in data/issues.jsonl."""

    number: int
    title: str
    body: str
    created_at: str
    reporter: str
    sigs: tuple[str, ...]

    @classmethod
    def from_json(cls, row: dict) -> "Issue":
        """Build an Issue from one JSONL row."""
        return cls(
            number=row["number"],
            title=row["title"],
            body=row.get("body") or "",
            created_at=row["created_at"],
            reporter=row["reporter"],
            sigs=tuple(row["sigs"]),
        )


@dataclass(frozen=True)
class Entity:
    """A routing signal pulled out of an issue."""

    name: str
    kind: EntityKind


@dataclass
class TeamScore:
    """One ranked team with its share of the score and its cheapest path (node names)."""

    team: str
    share: float
    path: list[str]


@dataclass
class RouteResult:
    """The router's answer, matching the POST /route response shape."""

    teams: list[TeamScore] = field(default_factory=list)
    confidence: float = 0.0
    entities_found: int = 0
    entities_unknown: int = 0

    def to_dict(self) -> dict:
        """Serialise to the documented JSON shape."""
        return asdict(self)

    @property
    def top_team(self) -> str | None:
        """The highest ranked team, or None when nothing was found."""
        return self.teams[0].team if self.teams else None
