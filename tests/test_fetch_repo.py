from datetime import date

from baton.repos import RepoProfile
from data import fetch_repo


def node(closer: dict | None = None, author: dict | None = None) -> dict:
    return {
        "number": 7,
        "title": "crash",
        "body": "x" * 50,
        "createdAt": "2026-01-02T00:00:00Z",
        "author": author or {"__typename": "User", "login": "rep"},
        "labels": {"nodes": [{"name": "b"}, {"name": "a"}]},
        "assignees": {"nodes": [{"login": "zed"}, {"login": "amy"}]},
        "timelineItems": {"nodes": [{"closer": closer}] if closer else []},
    }


def test_fixer_is_the_merged_pr_author_and_never_a_bot():
    merged = {"__typename": "PullRequest", "merged": True, "author": {"__typename": "User", "login": "dev"}}
    assert fetch_repo.fixer_of(node(merged)) == "dev"
    assert fetch_repo.fixer_of(node({**merged, "merged": False})) == ""
    assert fetch_repo.fixer_of(node({**merged, "author": {"__typename": "Bot", "login": "renovate"}})) == ""
    assert fetch_repo.fixer_of(node({"__typename": "Commit", "author": {"user": {"login": "c"}}})) == "c"
    assert fetch_repo.fixer_of(node()) == ""


def test_raw_record_sorts_labels_and_drops_bot_reporters():
    raw = fetch_repo.to_raw(node(author={"__typename": "User", "login": "dependabot[bot]"}))
    assert raw["labels"] == ["a", "b"] and raw["assignees"] == ["amy", "zed"]
    assert raw["reporter"] == "" and raw["created_at"] == "2026-01-02T00:00:00Z"


def test_search_filter_matches_each_signal():
    assert fetch_repo.signal_filter(RepoProfile(repo="a/b", prefix="T-"), ["T-libs", "C-bug"]) == 'label:"T-libs"'
    assert fetch_repo.signal_filter(RepoProfile(repo="a/b", signal="fixer"), []) == "linked:pr"
    assert fetch_repo.signal_filter(RepoProfile(repo="a/b", signal="assignee"), []) == ""


def test_windows_walk_back_to_the_start_without_gaps():
    spans = list(fetch_repo.windows(date(2026, 3, 1), date(2026, 1, 1)))
    assert spans[0][1] == date(2026, 3, 1) and spans[-1][0] == date(2026, 1, 1)
    assert all(newer[0] == older[1] for newer, older in zip(spans, spans[1:]))
