"""Merge, split and gap-filling passes as pure computations over a GraphState; the Learner writes what they return."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import sqrt

from baton.config import MIN_ENTITY_ISSUES, LearnParams
from baton.entities import extract_issue, kind_of
from baton.models import Issue
from baton.snapshots import GraphState, Link, Pair

COMPOUND_JOIN = "+"


def compound_name(a: str, b: str) -> str:
    """The compound entity for two co-occurring entities, e.g. `comp:kubelet+word:timeout`."""
    return COMPOUND_JOIN.join(sorted((a, b)))


def is_compound(name: str) -> bool:
    """Whether an entity name is a split compound."""
    return COMPOUND_JOIN in name


def with_compounds(names: list[str], vocabulary: Iterable[str]) -> list[str]:
    """The names plus every vocabulary compound whose parts are all among them."""
    present = set(names)
    return names + [c for c in vocabulary if is_compound(c) and all(p in present for p in c.split(COMPOUND_JOIN))]


def history_by_entity(state: GraphState) -> dict[str, dict[str, int]]:
    """Each entity's history path count per team."""
    by_entity: dict[str, dict[str, int]] = defaultdict(dict)
    for (entity, team), paths in state.history_paths.items():
        by_entity[entity][team] = paths
    return by_entity


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of two sparse team vectors."""
    dot = sum(value * b.get(team, 0.0) for team, value in a.items())
    norms = sqrt(sum(v * v for v in a.values())) * sqrt(sum(v * v for v in b.values()))
    return dot / norms if norms else 0.0


def merge_pairs(state: GraphState, params: LearnParams) -> list[Pair]:
    """Same-kind entity pairs, each seen in merge_min_hits+ issues, whose team profiles are near-identical and not yet merged."""
    history = history_by_entity(state)
    by_kind: dict[str, list[str]] = defaultdict(list)
    for entity, issues in sorted(state.entity_issues.items()):
        if issues >= params.merge_min_hits and not is_compound(entity):
            by_kind[kind_of(entity)].append(entity)
    profile = {
        entity: {t: link.strength for t, link in state.routes_out[entity].items()} if state.routes_out.get(entity) else history[entity]
        for names in by_kind.values()
        for entity in names
    }
    return [
        (a, b)
        for names in by_kind.values()
        for k, a in enumerate(names)
        for b in names[k + 1 :]
        if (a, b) not in state.same_as and cosine(profile[a], profile[b]) >= params.merge_similarity
    ]


def best_partner(state: GraphState, entity: str, taken: set[str], min_support: int) -> tuple[str, Counter, int] | None:
    """The co-occurring entity whose compound beats the entity's own top-team rate by the most issues, with team counts and support."""
    numbers = state.seen_in.get(entity, ())
    base: Counter = Counter()
    together: dict[str, Counter] = defaultdict(Counter)
    support: Counter = Counter()
    for number in numbers:
        past = state.history[number]
        base.update(past.teams)
        for other in set(past.entities) - {entity}:
            if not is_compound(other):
                support[other] += 1
                together[other].update(past.teams)
    if not base:
        return None
    base_rate = max(base.values()) / len(numbers)
    gains = {
        other: max(together[other].values()) - support[other] * base_rate
        for other in support
        if support[other] >= min_support and compound_name(entity, other) not in taken
    }
    best = max(sorted(gains), key=lambda other: gains[other], default=None)
    return (best, together[best], support[best]) if best is not None and gains[best] > 0 else None


def split_pass(state: GraphState, taken: set[str], params: LearnParams) -> dict[str, dict[str, Link]]:
    """New compounds for entities with split_min_misses+ misses and no dominant team, with ROUTES_TO links from the issues carrying both."""
    history = history_by_entity(state)
    compounds: dict[str, dict[str, Link]] = {}
    for entity, misses in sorted(state.entity_misses.items()):
        issues = state.entity_issues[entity]
        if misses < params.split_min_misses or is_compound(entity) or not history[entity]:
            continue
        if max(history[entity].values()) / issues > params.split_dominance:
            continue
        found = best_partner(state, entity, taken | set(compounds), params.split_min_support)
        if found is None:
            continue
        partner, teams, carried = found
        name = compound_name(entity, partner)
        compounds[name] = {team: Link(params.shortcut_scale * count / carried, hits=count) for team, count in sorted(teams.items())}
    return compounds


def needs_gap_fill(confidence: float, known: int, params: LearnParams) -> bool:
    """Whether a routed issue is too uncertain and too unfamiliar to trust."""
    return confidence < params.gap_confidence and known < params.gap_min_known


@dataclass
class ReservePool:
    """The reserve issues (older than the learning stream) with their extracted entities, indexed by entity name."""

    issues: list[tuple[Issue, list[str]]]
    by_entity: dict[str, list[int]]

    @classmethod
    def build(cls, reserve: Iterable[Issue]) -> "ReservePool":
        """Extract every reserve issue once and index it."""
        issues = [(issue, [entity.name for entity in extract_issue(issue)]) for issue in reserve]
        by_entity: dict[str, list[int]] = defaultdict(list)
        for k, (_, names) in enumerate(issues):
            for name in names:
                by_entity[name].append(k)
        return cls(issues, dict(by_entity))

    def pull(self, issue: Issue, unknown: list[str], state: GraphState, limit: int) -> list[int]:
        """Up to `limit` reserve issues older than `issue`, not yet history, sharing the most unknown entities (newest first)."""
        shared: Counter = Counter()
        for name in unknown:
            for k in self.by_entity.get(name, ()):
                past = self.issues[k][0]
                if past.created_at < issue.created_at and past.number not in state.history:
                    shared[k] += 1
        return sorted(shared, key=lambda k: (-shared[k], -k))[:limit]

    def vocabulary(self, picks: list[int], unknown: list[str]) -> list[str]:
        """The unknown entities that appear in at least MIN_ENTITY_ISSUES of the picked issues."""
        counts = Counter(name for k in picks for name in self.issues[k][1])
        return [name for name in unknown if counts[name] >= MIN_ENTITY_ISSUES]
