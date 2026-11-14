import gzip
import json
import random

import pytest

from baton.config import LEARNING_SIZE, TEST_SIZE
from baton.dataset import read_jsonl, split
from baton.models import Issue


def make_issue(number):
    return Issue(number, f"t{number}", "", f"2024-01-01T00:00:{number:05d}Z", "r", ("sig/node",))


def test_split_is_by_date_never_random():
    issues = [make_issue(n) for n in range(LEARNING_SIZE + TEST_SIZE)]
    random.Random(7).shuffle(issues)
    learning, test = split(issues)
    assert [i.number for i in learning] == list(range(LEARNING_SIZE))
    assert [i.number for i in test] == list(range(LEARNING_SIZE, LEARNING_SIZE + TEST_SIZE))
    assert learning[-1].created_at < test[0].created_at


def test_split_rejects_too_few_issues():
    with pytest.raises(ValueError):
        split([make_issue(1)])


def test_read_jsonl_falls_back_to_gzip(tmp_path):
    rows = [{"number": 2, "title": "b", "body": "", "created_at": "2024-02-01", "reporter": "r", "sigs": ["sig/node"]},
            {"number": 1, "title": "a", "body": None, "created_at": "2024-01-01", "reporter": "r", "sigs": ["sig/apps"]}]
    with gzip.open(tmp_path / "x.jsonl.gz", "wt") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)
    assert [i.number for i in read_jsonl(tmp_path / "x.jsonl")] == [1, 2]
