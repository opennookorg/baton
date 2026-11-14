"""Fetch closed kubernetes/kubernetes issues with sig/ labels into data/issues.jsonl and data/reserve.jsonl."""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx

from baton.config import ISSUES_FILE, RESERVE_FILE, RESERVE_SIZE, TOTAL_ISSUES


API_URL = "https://api.github.com/repos/kubernetes/kubernetes/issues"
CACHE_DIR = Path(os.environ.get("BATON_FETCH_CACHE", Path.home() / ".cache" / "baton" / "fetch_pages"))
MAX_BODY_CHARS = 20_000
MAX_ATTEMPTS = 6
FIRST_PAGE_PARAMS = {"state": "closed", "per_page": 100, "sort": "created", "direction": "desc"}


def github_token() -> str:
    """Return a GitHub token from GITHUB_TOKEN or the gh CLI, never echoing it."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def to_record(item: dict) -> dict | None:
    """Turn one API item into a saved record, or None when it is a PR or has no sig/ label."""
    if "pull_request" in item:
        return None
    labels = [label["name"] for label in item.get("labels", [])]
    sigs = sorted(name for name in labels if name.startswith("sig/"))
    if not sigs:
        return None
    return {
        "number": item["number"],
        "title": item["title"],
        "body": (item.get("body") or "")[:MAX_BODY_CHARS],
        "created_at": item["created_at"],
        "reporter": (item.get("user") or {}).get("login", ""),
        "sigs": sigs,
        "other_labels": sorted(name for name in labels if not name.startswith("sig/")),
    }


def wait_for_rate_limit(response: httpx.Response) -> float:
    """Return how many seconds to sleep before retrying, based on rate-limit headers."""
    if response.headers.get("retry-after"):
        return float(response.headers["retry-after"])
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = float(response.headers.get("x-ratelimit-reset", time.time() + 60))
        return max(reset - time.time(), 0) + 2
    return 0.0


def fetch_page(client: httpx.Client, url: str) -> tuple[list[dict], str | None]:
    """Fetch one page, retrying on errors and backing off on rate limits; return items and the next cursor URL."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            print(f"{type(error).__name__}, retrying", flush=True)
            time.sleep(2**attempt)
            continue
        if response.status_code == 200:
            if response.headers.get("x-ratelimit-remaining") == "0":
                time.sleep(wait_for_rate_limit(response))
            return response.json(), response.links.get("next", {}).get("url")
        pause = wait_for_rate_limit(response) if response.status_code in (403, 429) else 0.0
        pause = pause or 2**attempt
        print(f"HTTP {response.status_code}, sleeping {pause:.0f}s", flush=True)
        time.sleep(pause)
    raise RuntimeError(f"{url} failed after {MAX_ATTEMPTS} attempts")


def cached_page(step: int) -> Path:
    """Path of the cached qualifying records and next cursor for one page."""
    return CACHE_DIR / f"page_{step:05d}.json"


def collect(client: httpx.Client, needed: int) -> list[dict]:
    """Follow cursor pages newest first, resuming from cache, until `needed` unique qualifying issues are found."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    by_number: dict[int, dict] = {}
    url: str | None = str(httpx.URL(API_URL, params=FIRST_PAGE_PARAMS))
    step = 1
    while url and len(by_number) < needed:
        path = cached_page(step)
        if path.exists():
            payload = json.loads(path.read_text())
        else:
            items, next_url = fetch_page(client, url)
            payload = {"next": next_url, "records": [r for r in map(to_record, items) if r]}
            path.write_text(json.dumps(payload))
            print(f"page {step}: {len(payload['records'])} kept, {len(by_number) + len(payload['records'])} total", flush=True)
        for record in payload["records"]:
            by_number.setdefault(record["number"], record)
        url = payload["next"]
        step += 1
    return sorted(by_number.values(), key=lambda r: (r["created_at"], r["number"]), reverse=True)


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records oldest first as JSON lines."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["number"]))
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered))


def main() -> None:
    """Fetch, split into the newest issues and the older reserve, and save both files."""
    headers = {"Authorization": f"Bearer {github_token()}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    with httpx.Client(headers=headers, timeout=60) as client:
        records = collect(client, TOTAL_ISSUES + RESERVE_SIZE)
    if len(records) < TOTAL_ISSUES + RESERVE_SIZE:
        raise SystemExit(f"only {len(records)} qualifying issues found")
    issues = records[:TOTAL_ISSUES]
    reserve = records[TOTAL_ISSUES : TOTAL_ISSUES + RESERVE_SIZE]
    write_jsonl(ISSUES_FILE, issues)
    write_jsonl(RESERVE_FILE, reserve)
    print(f"wrote {len(issues)} issues to {ISSUES_FILE.name} and {len(reserve)} to {RESERVE_FILE.name}")


if __name__ == "__main__":
    main()
