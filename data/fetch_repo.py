"""Fetch closed issues of any GitHub repo with their labels, assignees and fixer, through GraphQL search in date windows."""

import gzip
import hashlib
import json
import os
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import httpx

from baton.repos import RepoProfile
from data.fetch_issues import MAX_BODY_CHARS, github_token

GRAPHQL_URL = "https://api.github.com/graphql"
CACHE_DIR = Path(os.environ.get("BATON_FETCH_CACHE", Path.home() / ".cache" / "baton" / "fetch_repo"))
SEARCH_CAP = 1_000
PAGE_SIZE = 50
WINDOW_DAYS = 30
MAX_ATTEMPTS = 8
ISSUE_FIELDS = """
number title body createdAt author { __typename login }
labels(first: 30) { nodes { name } }
assignees(first: 5) { nodes { login } }
timelineItems(itemTypes: [CLOSED_EVENT], last: 1) { nodes { ... on ClosedEvent { closer {
  __typename
  ... on PullRequest { merged author { __typename login } }
  ... on Commit { author { user { login } } }
} } } }
"""
SEARCH_QUERY = (
    "query($q: String!, $after: String, $size: Int!) { rateLimit { remaining resetAt } "
    "search(query: $q, type: ISSUE, first: $size, after: $after) { issueCount pageInfo { hasNextPage endCursor } "
    "nodes { ... on Issue { " + ISSUE_FIELDS + " } } } }"
)
REPO_QUERY = (
    "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { nameWithOwner createdAt "
    "object(expression: \"HEAD:\") { ... on Tree { entries { name type } } } } }"
)
LABELS_QUERY = (
    "query($owner: String!, $name: String!, $prefix: String!, $after: String) { repository(owner: $owner, name: $name) { "
    "labels(first: 100, query: $prefix, after: $after) { pageInfo { hasNextPage endCursor } nodes { name } } } }"
)


def is_bot(actor: dict | None) -> bool:
    """True for GitHub Apps and bot accounts, which are never owners."""
    return not actor or actor.get("__typename") == "Bot" or actor.get("login", "").endswith("[bot]")


def fixer_of(node: dict) -> str:
    """The author of the merged PR, or of the commit, that closed the issue; empty when a person closed it by hand."""
    events = node.get("timelineItems", {}).get("nodes") or [{}]
    closer = (events[-1] or {}).get("closer") or {}
    if closer.get("__typename") == "PullRequest" and closer.get("merged") and not is_bot(closer.get("author")):
        return closer["author"]["login"]
    if closer.get("__typename") == "Commit":
        return ((closer.get("author") or {}).get("user") or {}).get("login", "")
    return ""


def to_raw(node: dict) -> dict:
    """One search node as a raw record that every owner signal can read."""
    author = node.get("author") or {}
    return {
        "number": node["number"],
        "title": node["title"],
        "body": (node.get("body") or "")[:MAX_BODY_CHARS],
        "created_at": node["createdAt"],
        "reporter": "" if is_bot(author) else author.get("login", ""),
        "labels": sorted(label["name"] for label in node["labels"]["nodes"]),
        "assignees": sorted(a["login"] for a in node["assignees"]["nodes"]),
        "fixer": fixer_of(node),
    }


class GitHub:
    """A small GraphQL client with retries, rate-limit waits and a page cache."""

    def __init__(self) -> None:
        self.client = httpx.Client(headers={"Authorization": f"Bearer {github_token()}"}, timeout=120)

    def query(self, query: str, **variables) -> dict:
        """Run one GraphQL query, retrying server errors with backoff and waiting out rate limits."""
        for attempt in range(MAX_ATTEMPTS):
            response = self.client.post(GRAPHQL_URL, json={"query": query, "variables": variables})
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code == 200 and "data" in payload and not payload.get("errors"):
                limit = payload["data"].get("rateLimit") or {}
                if limit and limit["remaining"] < 50:
                    time.sleep(max(time.mktime(time.strptime(limit["resetAt"], "%Y-%m-%dT%H:%M:%SZ")) - time.mktime(time.gmtime()), 0) + 5)
                return payload["data"]
            pause = float(response.headers.get("retry-after", min(2**attempt, 120)))
            print(f"  github {response.status_code}: {str(payload.get('errors') or response.text)[:160]}; retry in {pause:.0f}s", flush=True)
            time.sleep(pause)
            if attempt >= 2:
                variables["size"] = max(10, variables.get("size", PAGE_SIZE) // 2)
        raise RuntimeError(f"GitHub GraphQL kept failing for {variables}")

    def search(self, q: str) -> list[dict]:
        """Every issue matching a search query (callers keep it under the 1,000-result cap), cached on disk."""
        cache = CACHE_DIR / f"{hashlib.sha1(q.encode()).hexdigest()}.json.gz"
        if cache.exists():
            with gzip.open(cache, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        records, after = [], None
        while True:
            result = self.query(SEARCH_QUERY, q=q, after=after, size=PAGE_SIZE)["search"]
            records += [to_raw(node) for node in result["nodes"] if node]
            if not result["pageInfo"]["hasNextPage"]:
                break
            after = result["pageInfo"]["endCursor"]
        cache.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(cache, "wt", encoding="utf-8") as handle:
            json.dump(records, handle)
        return records

    def count(self, q: str) -> int:
        """How many issues match a search query."""
        return self.query("query($q: String!) { search(query: $q, type: ISSUE, first: 1) { issueCount } }", q=q)["search"]["issueCount"]

    def repo_info(self, repo: str) -> dict:
        """The repo's current name (GitHub follows renames and transfers), creation date and top-level folders."""
        owner, name = repo.split("/")
        info = self.query(REPO_QUERY, owner=owner, name=name)["repository"]
        entries = (info.get("object") or {}).get("entries") or []
        return {
            "repo": info["nameWithOwner"],
            "created_at": info["createdAt"][:10],
            "folders": sorted(e["name"] for e in entries if e["type"] == "tree" and not e["name"].startswith(".")),
        }

    def labels(self, repo: str, prefix: str) -> list[str]:
        """Every label of the repo that starts with `prefix`."""
        owner, name = repo.split("/")
        found, after = [], None
        while True:
            page = self.query(LABELS_QUERY, owner=owner, name=name, prefix=prefix, after=after)["repository"]["labels"]
            found += [node["name"] for node in page["nodes"] if node["name"].startswith(prefix)]
            if not page["pageInfo"]["hasNextPage"]:
                return sorted(found)
            after = page["pageInfo"]["endCursor"]


def quoted(label: str) -> str:
    return '"' + label.replace('"', '\\"') + '"'


def signal_filter(profile: RepoProfile, labels: list[str]) -> str:
    """The search qualifier that keeps only issues this profile's signal can own, when search can express it."""
    if profile.signal == "label_prefix":
        return "label:" + ",".join(quoted(label) for label in labels if label.startswith(profile.prefix))
    if profile.signal == "labels":
        return "label:" + ",".join(quoted(label) for label in profile.labels)
    if profile.signal == "fixer":
        return "linked:pr"
    return ""


def window_records(github: GitHub, base: str, start: date, end: date) -> list[dict]:
    """Every issue created in [start, end) matching `base`, halving the window while it is over the search cap."""
    q = f"{base} created:{start.isoformat()}..{(end - timedelta(days=1)).isoformat()}"
    if (end - start).days > 1 and github.count(q) > SEARCH_CAP:
        middle = start + (end - start) // 2
        return window_records(github, base, start, middle) + window_records(github, base, middle, end)
    return github.search(q)


def windows(until: date, since: date) -> Iterator[tuple[date, date]]:
    """WINDOW_DAYS-long date windows, newest first, from `until` back to `since`."""
    end = until
    while end > since:
        start = max(end - timedelta(days=WINDOW_DAYS), since)
        yield start, end
        end = start


def fetch(profile: RepoProfile, labels: list[str], created_since: str, needed: int, today: date | None = None) -> list[dict]:
    """Walk back window by window until `needed` closed issues with an owner are found or the repo's start is reached."""
    github = GitHub()
    base = f"repo:{profile.repo} is:issue is:closed {signal_filter(profile, labels)}".strip()
    by_number: dict[int, dict] = {}
    owned = 0
    until = (today or date.today()) + timedelta(days=1)
    for start, end in windows(until, date.fromisoformat(created_since)):
        for record in window_records(github, base, start, end):
            if record["number"] not in by_number:
                by_number[record["number"]] = record
                owned += bool(profile.owners(record["labels"], record["fixer"], tuple(record["assignees"])))
        print(f"  {start}: {len(by_number)} closed, {owned} with an owner", flush=True)
        if owned >= needed:
            break
    return sorted(by_number.values(), key=lambda r: (r["created_at"], r["number"]))


def sample(repo: str, size: int = SEARCH_CAP) -> tuple[list[dict], dict]:
    """The newest `size` closed issues of a repo, unfiltered, plus repo info: what doctor inspects."""
    github = GitHub()
    info = github.repo_info(repo)
    repo = info["repo"]
    info["closed_issues"] = github.count(f"repo:{repo} is:issue is:closed")
    records: dict[int, dict] = {}
    for start, end in windows(date.today() + timedelta(days=1), date.fromisoformat(info["created_at"])):
        for record in window_records(github, f"repo:{repo} is:issue is:closed", start, end):
            records.setdefault(record["number"], record)
        if len(records) >= size:
            break
    newest = sorted(records.values(), key=lambda r: (r["created_at"], r["number"]))[-size:]
    return newest, info


def write_jsonl_gz(path: Path, rows: list[dict]) -> None:
    """Write rows as gzipped JSONL, oldest first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def read_jsonl_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
