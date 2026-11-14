"""Load the issue files and split them by date into the learning stream and the test set."""

import gzip
import json
from pathlib import Path

from baton.config import ISSUES_FILE, LEARNING_SIZE, RESERVE_FILE, TEST_SIZE
from baton.models import Issue


def read_jsonl(path: Path) -> list[Issue]:
    """Read issues from a JSONL file, or its .gz twin when only that exists, sorted oldest first."""
    gz_path = path.with_name(path.name + ".gz")
    opener = (lambda: path.open(encoding="utf-8")) if path.exists() else (lambda: gzip.open(gz_path, "rt", encoding="utf-8"))
    with opener() as handle:
        issues = [Issue.from_json(json.loads(line)) for line in handle if line.strip()]
    return sorted(issues, key=lambda issue: (issue.created_at, issue.number))


def load_issues(path: Path = ISSUES_FILE) -> list[Issue]:
    """Return the 2,000 main issues, oldest first."""
    return read_jsonl(path)


def load_reserve(path: Path = RESERVE_FILE) -> list[Issue]:
    """Return the reserve pool (all older than the main issues), oldest first."""
    return read_jsonl(path)


def split(issues: list[Issue] | None = None) -> tuple[list[Issue], list[Issue]]:
    """Return (learning, test): the oldest LEARNING_SIZE and the newest TEST_SIZE issues, both oldest first."""
    ordered = sorted(load_issues() if issues is None else issues, key=lambda issue: (issue.created_at, issue.number))
    if len(ordered) < LEARNING_SIZE + TEST_SIZE:
        raise ValueError(f"need {LEARNING_SIZE + TEST_SIZE} issues, got {len(ordered)}")
    return ordered[:LEARNING_SIZE], ordered[-TEST_SIZE:]
