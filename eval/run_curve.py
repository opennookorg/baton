"""Learning curve: per line, reset the graph, stream the learning issues in batches and score the frozen test set after each."""

import argparse
import json
import statistics
import time
from dataclasses import asdict, replace
from pathlib import Path

from baton import db, repos, snapshots
from baton.config import COUNT_ONLY, LearnParams, Techniques
from baton.dataset import load_reserve, split
from baton.entities import HIDE_SIG_MENTIONS
from baton.ids import IdTable
from baton.ingest import setup_graph
from baton.learn import BATON_PARAMS, BATON_TECHNIQUES, Learner
from baton.models import Issue
from baton.passes import ReservePool

LINES = {
    "frozen": COUNT_ONLY,
    "count_only": COUNT_ONLY,
    "reweight": Techniques(reweight=True, shortcuts=False, merging=False, splitting=False, gap_filling=False),
    "shortcuts": Techniques(reweight=False, shortcuts=True, merging=False, splitting=False, gap_filling=False),
    "merging": replace(COUNT_ONLY, merging=True),
    "splitting": replace(COUNT_ONLY, splitting=True),
    "gap_filling": replace(COUNT_ONLY, gap_filling=True),
    "baton": BATON_TECHNIQUES,
}
LINE_PARAMS = {
    "merging": replace(LearnParams(), merge_similarity=0.98, merge_min_hits=40),
    "splitting": replace(LearnParams(), split_min_misses=5, split_dominance=0.6, split_min_support=2),
    "gap_filling": replace(LearnParams(), gap_confidence=0.5, gap_min_known=12, gap_pull=10),
    "baton": BATON_PARAMS,
}
DEFAULT_LINES = ("frozen", "count_only", "reweight", "shortcuts", "merging", "splitting", "gap_filling", "baton")
SNAPSHOT_LINE = "baton"
AS_OF_ZERO = "as_of=0 is the empty graph: teams and vocabulary only, no history and no links, so routing returns no teams"


def score(learner: Learner, test: list[Issue]) -> tuple[dict, list[float]]:
    """Route every test issue with learning off; return top-1 and top-3 accuracy and per-route latency in ms."""
    top1 = top3 = 0
    latency: list[float] = []
    for issue in test:
        started = time.perf_counter()
        teams = [t.team for t in learner.route(issue).result.teams]
        latency.append((time.perf_counter() - started) * 1000)
        top1 += bool(teams) and teams[0] in issue.sigs
        top3 += any(team in issue.sigs for team in teams)
    return {"top1": round(top1 / len(test), 4), "top3": round(top3 / len(test), 4)}, latency


def fresh_learner(table: IdTable, techniques: Techniques, params: LearnParams, live: bool, reserve: ReservePool | None = None) -> Learner:
    """A learner on an empty graph (teams and vocabulary only), with its own copy of the table to grow."""
    table = IdTable(table.teams, table.entities)
    if live:
        setup_graph(table)
    return Learner(table, techniques, params, live=live, reserve=reserve)


def run_line(name: str, table: IdTable, learning: list[Issue], test: list[Issue], live: bool, save, reserve: ReservePool | None = None) -> dict:
    """Run one line and return its points and meta; `save` is called after every point."""
    sizes = repos.current().sizes
    params = LINE_PARAMS.get(name, LearnParams())
    learner = fresh_learner(table, LINES[name], params, live, reserve)
    stream = learning[: sizes.frozen] if name == "frozen" else learning
    points: list[dict] = []
    latency: list[float] = []
    stream_hits: list[bool] = []
    meta: dict = {"techniques": asdict(LINES[name]), "params": asdict(params), "graph": {}}

    def checkpoint(issues: int) -> None:
        accuracy, timings = score(learner, test)
        latency.extend(timings)
        points.append({"issues": issues, **accuracy})
        if live:
            meta["graph"][str(issues)] = db.counts()
        if live and name == SNAPSHOT_LINE and issues in sizes.snapshots:
            snapshots.save(learner.state, issues, {"line": name, "note": AS_OF_ZERO if issues == 0 else ""})
        meta.update(
            counters=dict(learner.state.counters),
            stream_top1=round(sum(stream_hits) / max(len(stream_hits), 1), 4),
            latency_ms={"median": round(statistics.median(latency), 2), "p95": round(sorted(latency)[int(0.95 * len(latency))], 2)},
        )
        print(f"{name:10s} {issues:5d} top1 {accuracy['top1']:.3f} top3 {accuracy['top3']:.3f}", flush=True)
        save(points, meta)

    if name != "frozen":
        checkpoint(0)
    for start in range(0, len(stream), sizes.batch):
        stream_hits += [learner.learn(issue)["correct"] for issue in stream[start : start + sizes.batch]]
        if name != "frozen":
            checkpoint(min(start + sizes.batch, len(stream)))
    if name == "frozen":
        checkpoint(sizes.frozen)
        flat = points[0]
        points[:] = [{**flat, "issues": n} for n in sorted({*range(0, len(learning) + 1, sizes.batch), len(learning)})]
        meta["note"] = f"graph built once from the first {sizes.frozen} learning issues and never updated; the same score at every x"
        save(points, meta)
    return {"points": points, "meta": meta}


def summary(curve: dict) -> dict:
    """Final-point gap and misroutes avoided per 1,000 issues, baton versus count_only."""
    lines = curve["lines"]
    if "baton" not in lines or "count_only" not in lines:
        return {}
    baton, count_only = lines["baton"][-1], lines["count_only"][-1]
    gap = baton["top1"] - count_only["top1"]
    return {"top1_gap": round(gap, 4), "top3_gap": round(baton["top3"] - count_only["top3"], 4), "misroutes_avoided_per_1000": round(gap * 1000)}


def write(path: Path, curve: dict) -> None:
    """Write the curve file atomically enough for a reader polling it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(curve, indent=1) + "\n")
    tmp.replace(path)


def main() -> None:
    """Run the requested lines and write results/curve.json after every point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", nargs="+", choices=list(LINES), default=list(DEFAULT_LINES))
    parser.add_argument("--offline", action="store_true", help="score on the in-memory mirror only, without HydraDB")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repo", default=None, help="owner/name of an onboarded repo; Kubernetes by default")
    args = parser.parse_args()
    with repos.use(repos.load(args.repo)):
        run(args.lines, args.offline, args.out)


def run(lines: list[str], offline: bool = False, out: Path | None = None) -> dict:
    """Run `lines` for the active repo and write its curve file after every point."""
    profile = repos.current()
    out = out or (profile.curve_file.with_name("curve_offline.json") if offline else profile.curve_file)
    curve = json.loads(out.read_text()) if out.exists() else {"lines": {}, "meta": {}}
    table = IdTable.load()
    learning, test = split()
    reserve = ReservePool.build(load_reserve())
    curve["meta"].update(
        repo=profile.repo,
        signal={"signal": profile.signal, "prefix": profile.prefix},
        mode="offline" if offline else "live",
        learning_issues=len(learning),
        test_issues=len(test),
        batch_size=profile.sizes.batch,
        frozen_size=profile.sizes.frozen,
        snapshots=list(profile.sizes.snapshots),
        hide_sig_mentions=HIDE_SIG_MENTIONS,
        params=asdict(LearnParams()),
        params_note="values tuned on the learning stream only (eval/tune_stream.py, results/tuning.json); each line's own params are in meta.lines",
        top1="top-ranked team is one of the issue's sigs",
        top3="any of the top three teams is one of the issue's sigs",
        as_of_zero=AS_OF_ZERO,
    )
    curve["meta"].setdefault("lines", {})
    for name in lines:
        def save(points: list[dict], meta: dict, name: str = name) -> None:
            curve["lines"][name] = points
            curve["meta"]["lines"][name] = meta
            curve["meta"]["summary"] = summary(curve)
            write(out, curve)

        run_line(name, table, learning, test, not offline, save, reserve)
    print(json.dumps(curve["meta"]["summary"]))
    return curve


if __name__ == "__main__":
    main()
