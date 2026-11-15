"""Load the issue files and split them by date into the learning stream and the test set."""

import gzip
import json
from pathlib import Path

from baton import repos
from baton.models import Issue


def read_jsonl(path: Path) -> list[Issue]:
    """Read issues from a JSONL file, or its .gz twin when only that exists, sorted oldest first."""
    gz_path = path.with_name(path.name + ".gz")
    opener = (lambda: path.open(encoding="utf-8")) if path.exists() else (lambda: gzip.open(gz_path, "rt", encoding="utf-8"))
    with opener() as handle:
        issues = [Issue.from_json(json.loads(line)) for line in handle if line.strip()]
    return sorted(issues, key=lambda issue: (issue.created_at, issue.number))


def load_issues(path: Path | None = None) -> list[Issue]:
    """Return the active repo's main issues, oldest first."""
    return read_jsonl(path or repos.current().issues_file)


def load_reserve(path: Path | None = None) -> list[Issue]:
    """Return the reserve pool (all older than the main issues), oldest first; empty when the repo has none."""
    path = path or repos.current().reserve_file
    if not path.exists() and not path.with_name(path.name + ".gz").exists():
        return []
    return read_jsonl(path)


def split(issues: list[Issue] | None = None) -> tuple[list[Issue], list[Issue]]:
    """Return (learning, test) for the active repo's sizes: the oldest `learning` and the newest `test` issues, oldest first."""
    sizes = repos.current().sizes
    ordered = sorted(load_issues() if issues is None else issues, key=lambda issue: (issue.created_at, issue.number))
    if len(ordered) < sizes.learning + sizes.test:
        raise ValueError(f"need {sizes.learning + sizes.test} issues, got {len(ordered)}")
    return ordered[: sizes.learning], ordered[-sizes.test :]
