"""Import and parse checks for the Locust load test, run in a subprocess to keep gevent patching out of pytest."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECK = """
import json, sys
from pathlib import Path
import baton.config
baton.config.ISSUES_FILE = Path(sys.argv[1])
import eval.loadtest as lt
from locust import HttpUser
assert issubclass(lt.RouteUser, HttpUser) and issubclass(lt.LearnUser, HttpUser)
assert lt.LearnUser.fixed_count > 0
print(json.dumps({"learning": [i["number"] for i in lt.LEARNING_ISSUES], "test": [i["number"] for i in lt.TEST_ISSUES]}))
"""


def run_check(issues_file: Path) -> dict:
    """Import the locustfile against a given issues file and return its splits."""
    done = subprocess.run([sys.executable, "-c", CHECK, str(issues_file)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_falls_back_to_builtin_sample(tmp_path):
    splits = run_check(tmp_path / "missing.jsonl")
    assert splits["learning"] and splits["test"]


def test_test_split_is_newest_by_created_at(tmp_path):
    issues_file = tmp_path / "issues.jsonl"
    rows = [{"number": n, "title": f"t{n}", "body": "", "created_at": f"2024-01-01T00:{n % 60:02d}:{n // 60:02d}Z", "reporter": "r", "sigs": ["node"]} for n in range(400)]
    issues_file.write_text("\n".join(json.dumps(row) for row in reversed(rows)))
    splits = run_check(issues_file)
    newest = sorted(rows, key=lambda row: row["created_at"])
    assert splits["test"] == [row["number"] for row in newest[-300:]]
    assert splits["learning"] == [row["number"] for row in newest[:-300]]
