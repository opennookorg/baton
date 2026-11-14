"""Simulated reorganisation on the offline mirror: from learning issue REORG_AT on, one team's work moves to another; compare how baton and count_only recover."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from baton.config import BATCH_SIZE, RESULTS_DIR, LearnParams
from baton.dataset import load_reserve, split
from baton.ids import IdTable
from baton.models import Issue
from baton.passes import ReservePool
from eval.run_curve import LINE_PARAMS, LINES, fresh_learner, score

RECOVERY_FILE = RESULTS_DIR / "recovery.json"
REORG_AT = 900
FROM_TEAM = "sig/scheduling"
TO_TEAM = "sig/apps"
RECOVERY_LINES = ("count_only", "baton")
NOTE = (
    "simulated: the real labels never changed. From learning issue {at} on, every {old} label is rewritten to {new} in the "
    "learning stream and in the test set used for scoring; run offline on the in-memory mirror, not HydraDB; reserve issues "
    "pulled by gap filling keep their old labels, like real history would"
)


def relabel(issue: Issue, old: str, new: str) -> Issue:
    """The issue with `old` replaced by `new` in its sigs."""
    if old not in issue.sigs:
        return issue
    return replace(issue, sigs=tuple(dict.fromkeys(new if sig == old else sig for sig in issue.sigs)))


def run_line(name: str, table: IdTable, learning: list[Issue], test: list[Issue], reserve: ReservePool, at: int, old: str, new: str) -> list[dict]:
    """Stream the learning issues with the reorg applied from `at` on, scoring every batch on the matching test labels."""
    learner = fresh_learner(table, LINES[name], LINE_PARAMS.get(name, LearnParams()), live=False, reserve=reserve)
    moved_test = [relabel(issue, old, new) for issue in test]
    moved_only = [issue for issue, original in zip(moved_test, test) if old in original.sigs]
    points: list[dict] = []
    for start in range(0, len(learning), BATCH_SIZE):
        for k, issue in enumerate(learning[start : start + BATCH_SIZE], start):
            learner.learn(relabel(issue, old, new) if k >= at else issue)
        issues = start + BATCH_SIZE
        after = issues >= at
        accuracy, _ = score(learner, moved_test if after else test)
        moved, _ = score(learner, moved_only if after else [issue for issue in test if old in issue.sigs])
        points.append({"issues": issues, **accuracy, "moved_top1": moved["top1"], "reorg": after})
        print(f"{name:10s} {issues:5d} top1 {accuracy['top1']:.3f} moved team top1 {moved['top1']:.3f}", flush=True)
    return points


def main() -> None:
    """Run the recovery lines and write results/recovery.json."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", type=int, default=REORG_AT)
    parser.add_argument("--from-team", default=FROM_TEAM)
    parser.add_argument("--to-team", default=TO_TEAM)
    parser.add_argument("--out", type=Path, default=RECOVERY_FILE)
    args = parser.parse_args()
    table = IdTable.load()
    learning, test = split()
    reserve = ReservePool.build(load_reserve())
    lines = {name: run_line(name, table, learning, test, reserve, args.at, args.from_team, args.to_team) for name in RECOVERY_LINES}
    result = {
        "meta": {
            "mode": "offline (simulated reorganisation)",
            "note": NOTE.format(at=args.at, old=args.from_team, new=args.to_team),
            "reorg_at": args.at,
            "from_team": args.from_team,
            "to_team": args.to_team,
            "moved_learning_issues": sum(args.from_team in issue.sigs for issue in learning[args.at :]),
            "moved_test_issues": sum(args.from_team in issue.sigs for issue in test),
            "moved_top1": f"top-1 on the test issues labelled {args.from_team} (scored as {args.to_team} once the reorg starts)",
        },
        "lines": lines,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({name: points[-1] for name, points in lines.items()}))


if __name__ == "__main__":
    main()
