"""No-graph baselines on the same split and the same entities: a one-hop lookup table and naive Bayes."""

import json
import math
from collections import Counter, defaultdict

from baton.config import RESULTS_DIR
from baton.dataset import split
from baton.ids import IdTable
from baton.ingest import issue_entities, issue_teams
from baton.models import Issue

NO_GRAPH_FILE = RESULTS_DIR / "no_graph.json"


class Lookup:
    """Entity to team counts in a flat table: score(team) = sum over entities of P(team | entity)."""

    def __init__(self) -> None:
        self.counts: dict[str, Counter] = defaultdict(Counter)

    def learn(self, entities: list[str], teams: list[str]) -> None:
        for entity in set(entities):
            self.counts[entity].update(teams)

    def rank(self, entities: list[str]) -> list[str]:
        scores: Counter = Counter()
        for entity in set(entities):
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
        known = [e for e in set(entities) if e in self.vocabulary]
        if not known:
            return []
        issues = sum(self.team_issues.values())
        size = len(self.vocabulary)

        def log_score(team: str) -> float:
            seen = self.team_entities[team]
            total = sum(seen.values())
            return math.log(self.team_issues[team] / issues) + sum(math.log((seen[e] + 1) / (total + size)) for e in known)

        return sorted(self.team_issues, key=log_score, reverse=True)


def accuracy(model, rows: list[tuple[list[str], list[str]]]) -> dict:
    """Top-1 and top-3 accuracy on (entities, teams) rows."""
    top1 = top3 = 0
    for entities, teams in rows:
        ranked = model.rank(entities)[:3]
        top1 += bool(ranked) and ranked[0] in teams
        top3 += any(team in teams for team in ranked)
    return {"top1": round(top1 / len(rows), 4), "top3": round(top3 / len(rows), 4)}


def rows(issues: list[Issue], table: IdTable) -> list[tuple[list[str], list[str]]]:
    """Each issue as (known entities, team labels)."""
    return [(issue_entities(issue, table), issue_teams(issue, table)) for issue in issues]


def run(learning: list[Issue], test: list[Issue], table: IdTable) -> dict:
    """Train each baseline on every learning issue and score the test set."""
    train, held_out = rows(learning, table), rows(test, table)
    results = {}
    for name, model in (("lookup", Lookup()), ("naive_bayes", NaiveBayes())):
        for entities, teams in train:
            model.learn(entities, teams)
        results[name] = accuracy(model, held_out)
    return results


def main() -> None:
    """Write results/no_graph.json."""
    learning, test = split()
    results = run(learning, test, IdTable.load())
    payload = {
        "lines": results,
        "meta": {
            "learning_issues": len(learning),
            "test_issues": len(test),
            "note": "same time split and same extracted entities as the graph lines; no graph, no paths, no learning passes",
        },
    }
    NO_GRAPH_FILE.write_text(json.dumps(payload, indent=1) + "\n")
    for name, scores in results.items():
        print(f"{name:12s} top1 {scores['top1']:.3f} top3 {scores['top3']:.3f}")


if __name__ == "__main__":
    main()
