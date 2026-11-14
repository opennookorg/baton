"""Locust load test: /route under load while /learn writes, saving median and p95 per endpoint."""

import itertools
import json
import random
import sys

from locust import HttpUser, between, events, task
from locust.main import main as locust_main

from baton.config import ISSUES_FILE, RESULTS_DIR, TEST_SIZE

LOADTEST_FILE = RESULTS_DIR / "loadtest.json"
DEFAULT_ARGS = ["--headless", "-u", "20", "-r", "5", "-t", "60s", "-H", "http://localhost:8000"]

BUILTIN_ISSUES = [
    {"number": 1, "title": "kubelet panics on node restart", "body": "pkg/kubelet/kubelet.go nil pointer dereference after reboot", "created_at": "2024-01-01T00:00:00Z", "reporter": "alice", "sigs": ["node"]},
    {"number": 2, "title": "PVC stuck in Pending with CSI driver", "body": "pkg/volume/csi attach timeout, error: timed out waiting for the condition", "created_at": "2024-01-02T00:00:00Z", "reporter": "bob", "sigs": ["storage"]},
    {"number": 3, "title": "kubectl apply drops annotations", "body": "staging/src/k8s.io/kubectl server-side apply loses metadata.annotations", "created_at": "2024-01-03T00:00:00Z", "reporter": "carol", "sigs": ["cli"]},
    {"number": 4, "title": "Service ClusterIP not reachable after kube-proxy restart", "body": "pkg/proxy/iptables rules missing, connection refused", "created_at": "2024-01-04T00:00:00Z", "reporter": "dave", "sigs": ["network"]},
    {"number": 5, "title": "scheduler ignores pod topology spread", "body": "pkg/scheduler/framework/plugins/podtopologyspread skew not respected", "created_at": "2024-01-05T00:00:00Z", "reporter": "erin", "sigs": ["scheduling"]},
    {"number": 6, "title": "apiserver watch cache returns stale list", "body": "staging/src/k8s.io/apiserver/pkg/storage/cacher resourceVersion too old", "created_at": "2024-01-06T00:00:00Z", "reporter": "frank", "sigs": ["api-machinery"]},
]


def load_splits() -> tuple[list[dict], list[dict]]:
    """Return (learning stream, test split) from data/issues.jsonl by date, else the built-in sample."""
    if not ISSUES_FILE.exists():
        return BUILTIN_ISSUES, BUILTIN_ISSUES
    rows = sorted((json.loads(line) for line in ISSUES_FILE.read_text().splitlines() if line.strip()), key=lambda row: row["created_at"])
    test = rows[-TEST_SIZE:]
    return rows[:-TEST_SIZE] or test, test


LEARNING_ISSUES, TEST_ISSUES = load_splits()
LEARNING_STREAM = itertools.cycle(LEARNING_ISSUES)


class RouteUser(HttpUser):
    """Routes test-split issues as fast as a triage client would."""

    weight = 1
    wait_time = between(0.1, 0.5)

    @task
    def route(self):
        issue = random.choice(TEST_ISSUES)
        self.client.post("/route", json={"title": issue["title"], "body": issue.get("body") or ""}, name="/route")


class LearnUser(HttpUser):
    """Feeds learning-stream issues to /learn in date order while routing runs."""

    fixed_count = 2
    wait_time = between(0.5, 1.0)

    @task
    def learn(self):
        issue = next(LEARNING_STREAM)
        self.client.post("/learn", json={**issue, "team": issue["sigs"][0]}, name="/learn")


def summarize(stats) -> dict:
    """Return median and p95 response times (ms) per endpoint plus the aggregate."""
    rows = {f"{entry.method} {entry.name}": entry for entry in stats.entries.values()}
    rows["Aggregated"] = stats.total
    return {
        name: {
            "requests": entry.num_requests,
            "failures": entry.num_failures,
            "median_ms": entry.median_response_time,
            "p95_ms": entry.get_response_time_percentile(0.95),
        }
        for name, entry in rows.items()
    }


@events.test_stop.add_listener
def write_results(environment, **kwargs):
    """Save the per-endpoint summary to results/loadtest.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {"host": environment.host, "users": environment.parsed_options.num_users if environment.parsed_options else None, "endpoints": summarize(environment.stats)}
    LOADTEST_FILE.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.argv = ["locust", "-f", __file__, *DEFAULT_ARGS, *sys.argv[1:]]
    sys.exit(locust_main())
