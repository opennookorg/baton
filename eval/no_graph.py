"""No-graph baselines on the same split and the same entities: a one-hop lookup table and naive Bayes."""

import argparse
import json
import math
from collections import Counter, defaultdict

from baton import repos
from baton.dataset import split
from baton.ids import IdTable
from baton.ingest import issue_entities, issue_teams
from baton.models import Issue
from eval.recovery import FROM_TEAM, REORG_AT, TO_TEAM

Row = tuple[list[str], list[str]]


class Lookup:
    """Entity to team counts in a flat table: score(team) = sum over entities of P(team | entity)."""

    def __init__(self) -> None:
        self.counts: dict[str, Counter] = defaultdict(Counter)

    def learn(self, entities: list[str], teams: list[str]) -> None:
        for entity in set(entities):
            self.counts[entity].update(teams)

    def rank(self, entities: list[str]) -> list[str]:
        scores: Counter = Counter()
        for entity in sorted(set(entities)):
            seen = self.counts.get(entity)
            if seen:
                total = sum(seen.values())
                for team, n in seen.items():
                    scores[team] += n / total
        return [team for team, _ in scores.most_common()]


class NaiveBayes:
    """Multinomial naive Bayes over the issue's entities, with add-one smoothing."""

    def __init__(self) -> None:
        self.team_issues: Counter = Counter()
        self.team_entities: dict[str, Counter] = defaultdict(Counter)
        self.vocabulary: set[str] = set()

    def learn(self, entities: list[str], teams: list[str]) -> None:
        for team in teams:
            self.team_issues[team] += 1
            self.team_entities[team].update(set(entities))
        self.vocabulary |= set(entities)

    def rank(self, entities: list[str]) -> list[str]:
        known = sorted(e for e in set(entities) if e in self.vocabulary)
        if not known:
            return []
        issues = sum(self.team_issues.values())
        size = len(self.vocabulary)

        def log_score(team: str) -> float:
            seen = self.team_entities[team]
            total = sum(seen.values())
            return math.log(self.team_issues[team] / issues) + sum(math.log((seen[e] + 1) / (total + size)) for e in known)

        return sorted(self.team_issues, key=log_score, reverse=True)


class Biggest:
    """Always the team with the most issues so far, whatever the issue says."""

    def __init__(self) -> None:
        self.team_issues: Counter = Counter()

    def learn(self, entities: list[str], teams: list[str]) -> None:
        self.team_issues.update(teams)

    def rank(self, entities: list[str]) -> list[str]:
        return [team for team, _ in self.team_issues.most_common()]


MODELS = {"lookup": Lookup, "naive_bayes": NaiveBayes, "always_biggest": Biggest}


def accuracy(model, rows: list[Row]) -> dict:
    """Top-1 and top-3 accuracy on (entities, teams) rows."""
    top1 = top3 = 0
    for entities, teams in rows:
        ranked = model.rank(entities)[:3]
        top1 += bool(ranked) and ranked[0] in teams
        top3 += any(team in teams for team in ranked)
    return {"top1": round(top1 / len(rows), 4), "top3": round(top3 / len(rows), 4)}


def rows(issues: list[Issue], table: IdTable) -> list[Row]:
    """Each issue as (known entities, team labels)."""
    return [(issue_entities(issue, table), issue_teams(issue, table)) for issue in issues]


def stream(model, learning: list[Row], scored_on) -> dict:
    """Learn the stream one issue at a time, scoring each issue before learning it and `scored_on(k)` every batch."""
    batch = repos.current().sizes.batch
    hits: list[bool] = []
    points: list[dict] = []
    for k, (entities, teams) in enumerate(learning, 1):
        ranked = model.rank(entities)
        hits.append(bool(ranked) and ranked[0] in teams)
        model.learn(entities, teams)
        if k % batch == 0 or k == len(learning):
            test, moved = scored_on(k)
            points.append({"issues": k, **accuracy(model, test), **({"moved_top1": accuracy(model, moved)["top1"]} if moved else {})})
    return {"points": points, "stream_top1": round(sum(hits) / len(hits), 4)}


def reorg(issue_rows: list[Row], at: int, old: str, new: str) -> list[Row]:
    """Rows with `old` relabelled `new` from position `at` on."""
    return [(entities, [new if t == old else t for t in dict.fromkeys(teams)] if k >= at else teams) for k, (entities, teams) in enumerate(issue_rows)]


def run(learning: list[Issue], test: list[Issue], table: IdTable) -> dict:
    """Stream each baseline over the learning issues, plus the simulated Kubernetes reorg used by eval/recovery.py."""
    train, held_out = rows(learning, table), rows(test, table)
    if not repos.current().is_kubernetes:
        return {name: final(stream(model(), train, lambda k: (held_out, None))) for name, model in MODELS.items()}
    moved_test = reorg(held_out, 0, FROM_TEAM, TO_TEAM)
    moved = [k for k, (_, teams) in enumerate(held_out) if FROM_TEAM in teams]

    def reorg_scored_on(k: int) -> tuple[list[Row], list[Row]]:
        rows_now = moved_test if k >= REORG_AT else held_out
        return rows_now, [rows_now[i] for i in moved]

    results = {}
    for name, model in MODELS.items():
        line = stream(model(), train, lambda k: (held_out, None))
        recovery = stream(model(), reorg(train, REORG_AT, FROM_TEAM, TO_TEAM), reorg_scored_on)
        results[name] = {**final(line), "recovery": recovery["points"]}
    return results


def final(line: dict) -> dict:
    """A streamed line as its last point, its stream accuracy and every point."""
    return {**line["points"][-1], "stream_top1": line["stream_top1"], "points": line["points"]}


def main() -> None:
    """Write the active repo's no_graph.json."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/name of an onboarded repo; Kubernetes by default")
    with repos.use(repos.load(parser.parse_args().repo)):
        write()


def write() -> dict:
    """Run every baseline for the active repo and save its no_graph.json."""
    learning, test = split()
    results = run(learning, test, IdTable.load())
    kubernetes = repos.current().is_kubernetes
    payload = {
        "lines": results,
        "meta": {
            "learning_issues": len(learning),
            "test_issues": len(test),
            "note": "same time split and same extracted entities as the graph lines; learned one issue at a time with no graph, no paths and no learning passes; stream_top1 scores each learning issue before it is learned",
            **({"recovery_note": f"after issue {REORG_AT}, {FROM_TEAM} is relabelled {TO_TEAM} in the stream; points from {REORG_AT} on are scored on the relabelled test set (eval/recovery.py)"} if kubernetes else {}),
        },
    }
    path = repos.current().no_graph_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n")
    for name, line in results.items():
        print(f"{name:14s} test top1 {line['top1']:.3f} top3 {line['top3']:.3f} stream top1 {line['stream_top1']:.3f}")
    return payload


if __name__ == "__main__":
    main()
