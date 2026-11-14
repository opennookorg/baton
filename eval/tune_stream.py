"""Tune merge, split and gap-filling values and pick baton's techniques on the learning stream only (prequential top-1); the test set is never scored."""

import itertools
import json
from dataclasses import asdict, replace

from baton.config import COUNT_ONLY, RESULTS_DIR, LearnParams, Techniques
from baton.dataset import load_reserve, split
from baton.ids import IdTable
from baton.learn import Learner
from baton.passes import ReservePool

TUNING_FILE = RESULTS_DIR / "tuning.json"
BASE_PARAMS = LearnParams()
REWEIGHT_SHORTCUTS = Techniques(reweight=True, shortcuts=True, merging=False, splitting=False, gap_filling=False)
MIN_GAIN = 0.003
GRIDS = {
    "merging": {"merge_similarity": (0.9, 0.95, 0.98, 0.99, 0.995), "merge_min_hits": (10, 20, 40)},
    "splitting": {"split_min_misses": (5, 10, 20), "split_dominance": (0.4, 0.5, 0.6), "split_min_support": (2, 3, 5, 8)},
    "gap_filling": {"gap_confidence": (0.4, 0.5, 0.6), "gap_min_known": (2, 3, 5, 8, 12), "gap_pull": (10, 20, 40)},
}


def stream_top1(learning: list, techniques: Techniques, params: LearnParams, reserve: ReservePool) -> float:
    """Prequential top-1: each learning issue is routed before its answer is revealed."""
    learner = Learner(IdTable.load(), techniques, params, live=False, reserve=reserve)
    hits = [learner.learn(issue)["correct"] for issue in learning]
    return round(sum(hits) / len(hits), 4)


def best_values(report: dict, technique: str, base: str) -> dict:
    """The grid values with the highest stream top-1 for one technique on one base."""
    return max(report["grids"][technique], key=lambda row: row[base])["params"]


def select(learning: list, report: dict, reserve: ReservePool) -> dict:
    """Greedy forward selection on reweight + shortcuts: keep a technique only if it adds MIN_GAIN or more stream top-1."""
    techniques, params = REWEIGHT_SHORTCUTS, BASE_PARAMS
    score = report["bases"]["reweight_shortcuts"]
    steps = []
    remaining = list(GRIDS)
    while remaining:
        trials = {
            t: (replace(techniques, **{t: True}), replace(params, **best_values(report, t, "reweight_shortcuts")))
            for t in remaining
        }
        scores = {t: stream_top1(learning, *trial, reserve) for t, trial in trials.items()}
        best = max(sorted(scores), key=lambda t: scores[t])
        steps.append({"from": score, "tried": scores})
        print("select", steps[-1], flush=True)
        if scores[best] - score < MIN_GAIN:
            break
        techniques, params = trials[best]
        score = scores[best]
        remaining.remove(best)
    return {"min_gain": MIN_GAIN, "steps": steps, "techniques": asdict(techniques), "params": asdict(params), "stream_top1": score}


def main() -> None:
    """Grid each technique on count_only and on reweight + shortcuts, then select baton's techniques; write results/tuning.json."""
    learning, _ = split()
    reserve = ReservePool.build(load_reserve())
    if TUNING_FILE.exists():
        report = json.loads(TUNING_FILE.read_text())
        report["selection"] = select(learning, report, reserve)
        TUNING_FILE.write_text(json.dumps(report, indent=1) + "\n")
        return
    report: dict = {"metric": "prequential top-1 on the 1,700 learning issues", "bases": {}, "grids": {}}
    bases = {"count_only": COUNT_ONLY, "reweight_shortcuts": REWEIGHT_SHORTCUTS}
    for base, techniques in bases.items():
        report["bases"][base] = stream_top1(learning, techniques, BASE_PARAMS, reserve)
    for technique, grid in GRIDS.items():
        rows = []
        for values in itertools.product(*grid.values()):
            params = replace(BASE_PARAMS, **dict(zip(grid, values)))
            row = {"params": dict(zip(grid, values))}
            for base, techniques in bases.items():
                row[base] = stream_top1(learning, replace(techniques, **{technique: True}), params, reserve)
            rows.append(row)
            print(technique, row, flush=True)
        report["grids"][technique] = sorted(rows, key=lambda r: -(r["count_only"] + r["reweight_shortcuts"]))
    report["base_params"] = asdict(BASE_PARAMS)
    report["selection"] = select(learning, report, reserve)
    TUNING_FILE.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
