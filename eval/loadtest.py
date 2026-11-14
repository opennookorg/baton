"""Locust load test: /route under load while /learn writes reserve-pool issues, saving median and p95 per endpoint."""

import itertools
import json
import random
import sys

import httpx
from locust import HttpUser, between, events, task
from locust.main import main as locust_main

from baton.config import ISSUES_FILE, RESERVE_FILE, RESULTS_DIR, TEST_SIZE

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


def read_rows(path) -> list[dict]:
    """Rows of a JSONL issues file sorted by created_at, or [] when it is missing."""
    if not path.exists():
        return []
    return sorted((json.loads(line) for line in path.read_text().splitlines() if line.strip()), key=lambda row: row["created_at"])


def load_splits() -> tuple[list[dict], list[dict]]:
    """Return (learning stream, test split) from data/issues.jsonl by date, else the built-in sample."""
    rows = read_rows(ISSUES_FILE)
    if not rows:
        return BUILTIN_ISSUES, BUILTIN_ISSUES
    test = rows[-TEST_SIZE:]
    return rows[:-TEST_SIZE] or test, test


LEARNING_ISSUES, TEST_ISSUES = load_splits()
LEARN_ISSUES = read_rows(RESERVE_FILE) or LEARNING_ISSUES
LEARN_STREAM = itertools.cycle(reversed(LEARN_ISSUES))


class RouteUser(HttpUser):
    """Routes test-split issues as fast as a triage client would."""

    weight = 1
    wait_time = between(0.1, 0.5)

    @task
    def route(self):
        issue = random.choice(TEST_ISSUES)
        self.client.post("/route", json={"title": issue["title"], "body": issue.get("body") or ""}, name="/route")


class LearnUser(HttpUser):
    """Feeds reserve-pool issues (real new writes; ones the graph already holds are no-ops) to /learn, newest first, while routing runs."""

    fixed_count = 2
    wait_time = between(0.5, 1.0)

    @task
    def learn(self):
        issue = next(LEARN_STREAM)
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


STATS_BEFORE: dict = {}


def fetch_stats(host: str) -> dict:
    """GET /stats from the API under test, or {} if it does not answer."""
    try:
        return httpx.get(f"{host}/stats", timeout=30).json()
    except (httpx.HTTPError, ValueError):
        return {}


@events.test_start.add_listener
def remember_stats(environment, **kwargs):
    """Record /stats before the run so the report can say how many real learning steps ran."""
    STATS_BEFORE.update(fetch_stats(environment.host))


@events.test_stop.add_listener
def write_results(environment, **kwargs):
    """Save the per-endpoint summary and the /stats change to results/loadtest.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    after = fetch_stats(environment.host)
    report = {
        "host": environment.host,
        "users": environment.parsed_options.num_users if environment.parsed_options else None,
        "endpoints": summarize(environment.stats),
        "stats_before": dict(STATS_BEFORE),
        "stats_after": after,
    }
    LOADTEST_FILE.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.argv = ["locust", "-f", __file__, *DEFAULT_ARGS, *sys.argv[1:]]
    sys.exit(locust_main())
