"""Onboard any GitHub repo end to end: inspect its owner signals, fetch its closed issues, learn its graph and evaluate it."""

import argparse
import json
from dataclasses import asdict, replace

from baton import doctor, repos
from baton.config import MIN_ENTITY_ISSUES, RESERVE_SIZE, TOTAL_ISSUES
from baton.dataset import load_issues, load_reserve, split
from baton.entities import build_vocabulary
from baton.ids import build_table
from baton.repos import RepoProfile
from data import fetch_repo
from eval import no_graph, run_curve

CASE_STUDY_LINES = ("frozen", "count_only", "baton")


def diagnose(repo: str) -> tuple[dict, dict]:
    """Sample the repo's newest closed issues, report every owner signal and save the report next to its data."""
    records, info = fetch_repo.sample(repo)
    report = doctor.diagnose(repo, records, info) | {"folders": info["folders"], "created_at": info["created_at"]}
    path = RepoProfile(repo=repo).data_dir / "doctor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n")
    print(doctor.report_text(report), flush=True)
    return report, info


def profile_from(repo: str, report: dict, signal: str | None, prefix: str | None) -> RepoProfile:
    """The doctor's recommendation, or the signal the caller forced, as a profile."""
    best = report["recommended"] or {}
    chosen = RepoProfile(
        repo=repo,
        signal=signal or best.get("signal", "fixer"),
        prefix=prefix if prefix is not None else best.get("prefix", ""),
        path_roots=tuple(report["folders"]),
    )
    return replace(chosen, doctor={"verdict": report["verdict"], "recommended": best, "closed_issues": report["closed_issues"]})


def owned_rows(profile: RepoProfile, records: list[dict]) -> list[dict]:
    """Raw records with an owner, in the issue-file shape: owners go in `sigs`, every other label in `other_labels`."""
    rows = []
    for record in records:
        owners = profile.owners(record["labels"], record["fixer"], tuple(record["assignees"]))
        if owners:
            rest = sorted(label for label in record["labels"] if label not in owners)
            fields = {key: record[key] for key in ("number", "title", "body", "created_at", "reporter")}
            rows.append(fields | {"sigs": owners, "other_labels": rest})
    return sorted(rows, key=lambda row: (row["created_at"], row["number"]))


def fetch(profile: RepoProfile, created_at: str) -> RepoProfile:
    """Fetch enough owned closed issues for the full split and reserve, write the issue files and size the profile."""
    sizes = repos.Sizes.scaled(TOTAL_ISSUES + RESERVE_SIZE)
    labels = fetch_repo.GitHub().labels(profile.repo, profile.prefix) if profile.signal == "label_prefix" else []
    records = fetch_repo.fetch(profile, labels, created_at, sizes.total + sizes.reserve)
    fetch_repo.write_jsonl_gz(profile.raw_file, records)
    rows = owned_rows(profile, records)
    available = min(len(rows), sizes.total + sizes.reserve)
    profile = replace(
        profile,
        available=available,
        hide_terms=tuple(sorted({o for row in rows for o in row["sigs"]})) if profile.signal in ("label_prefix", "labels") else (),
    )
    keep = rows[-available:] if available else []
    total = profile.sizes.total
    fetch_repo.write_jsonl_gz(profile.issues_file.with_name(profile.issues_file.name + ".gz"), keep[-total:])
    fetch_repo.write_jsonl_gz(profile.reserve_file.with_name(profile.reserve_file.name + ".gz"), keep[:-total])
    profile.save()
    print(f"{profile.repo}: {len(records)} closed fetched, {len(rows)} with an owner, {available} kept; sizes {profile.sizes}", flush=True)
    return profile


def build_ids() -> None:
    """Build the active repo's ID table from its owners and learning-stream vocabulary."""
    issues, reserve = load_issues(), load_reserve()
    learning, _ = split(issues)
    table = build_table({o for issue in issues + reserve for o in issue.sigs}, build_vocabulary(learning, MIN_ENTITY_ISSUES))
    table.save()
    print(f"{len(table.teams)} owners and {len(table.entities)} entities in {repos.current().table_file}", flush=True)


def evaluate(lines: tuple[str, ...] = CASE_STUDY_LINES) -> dict:
    """Run the graph lines live (saving routing snapshots) and the no-graph baselines; return the final scores."""
    curve = run_curve.run(list(lines))
    baselines = no_graph.write()
    scores = {name: points[-1] for name, points in curve["lines"].items()}
    scores |= {name: {"top1": line["top1"], "top3": line["top3"]} for name, line in baselines["lines"].items()}
    path = repos.current().results_dir / "summary.json"
    path.write_text(json.dumps({"repo": repos.current().repo, "scores": scores, "sizes": asdict(repos.current().sizes)}, indent=1) + "\n")
    for name, score in scores.items():
        print(f"{name:14s} top1 {score['top1']:.3f} top3 {score['top3']:.3f}", flush=True)
    return scores


def onboard(repo: str, signal: str | None = None, prefix: str | None = None, force: bool = False) -> dict:
    """Doctor, fetch, build and evaluate one repo; stop early with the doctor's reason when it cannot be routed."""
    report, info = diagnose(repo)
    if report["verdict"] != "ok" and not force and signal is None:
        print(f"not onboarding {repo}: {report['verdict']}", flush=True)
        return {"repo": repo, "verdict": report["verdict"]}
    profile = fetch(profile_from(repo, report, signal, prefix), info["created_at"])
    if profile.sizes.total < doctor.MIN_OWNED and not force:
        print(f"not onboarding {repo}: only {profile.available} owned closed issues, Baton needs {doctor.MIN_OWNED}", flush=True)
        return {"repo": repo, "verdict": "too small"}
    with repos.use(profile):
        build_ids()
        return {"repo": repo, "verdict": "ok", "scores": evaluate()}


def main() -> None:
    """Command line: `doctor` only inspects; `onboard` runs every step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "onboard", "evaluate"))
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--signal", choices=repos.SIGNALS, default=None, help="override the doctor's recommendation")
    parser.add_argument("--prefix", default=None, help="label prefix for --signal label_prefix")
    parser.add_argument("--force", action="store_true", help="onboard even when the doctor says the repo does not fit")
    args = parser.parse_args()
    if args.command == "doctor":
        diagnose(args.repo)
    elif args.command == "evaluate":
        with repos.use(repos.load(args.repo)):
            evaluate()
    else:
        onboard(args.repo, args.signal, args.prefix, args.force)


if __name__ == "__main__":
    main()
