import json
from dataclasses import replace

import pytest

from baton import service
from baton.learn import Learner
from tests.test_learn import LEARNED, PARAMS
from tests.test_router import ISSUES, NET, NODE, small_table


@pytest.fixture
def offline(monkeypatch, tmp_path):
    table = small_table()
    learner = Learner(table, LEARNED, PARAMS, live=False)
    for issue in ISSUES:
        learner.learn(issue)
    learner.end_batch()
    monkeypatch.setattr(service, "table", lambda: table)
    monkeypatch.setattr(service, "learner", lambda: learner)
    monkeypatch.setattr(service, "LIVE_STATE_FILE", tmp_path / "live_state.json")
    return learner


def test_graph_around_unknown_entity_is_empty(offline):
    assert service.graph_around("no-such-entity") == {"nodes": [], "links": []}


def test_graph_around_resolves_bare_names_and_matches_the_contract(offline):
    graph = service.graph_around("kubelet")
    ids = {node["id"] for node in graph["nodes"]}
    assert {node["label"] for node in graph["nodes"]} <= {"Team", "Entity", "Issue"}
    assert {"kubelet", NODE} <= {node["name"] for node in graph["nodes"]}
    assert all(link["source"] in ids and link["target"] in ids for link in graph["links"])
    assert {"ROUTES_TO", "SEEN_IN", "OWNED_BY"} >= {link["type"] for link in graph["links"]}
    json.dumps(graph)


def test_lookup_tools_read_the_learned_graph(offline):
    similar = service.similar_past_issues("kube-proxy dns broken", "")
    assert similar and similar[0]["team"] == NET and "kube-proxy" in similar[0]["shared"]
    assert {row["team"] for row in service.reporter_history("zz-test-alice")} == {NODE, NET}
    assert service.reporter_history("nobody") == []
    profile = service.team_profile(NODE)
    assert profile and profile[0]["strength"] >= profile[-1]["strength"]


def test_record_outcome_learns_and_saves_state(offline):
    before = offline.state.counters["issues_learned"]
    issue = replace(ISSUES[0], number=ISSUES[0].number + 10_000)
    result = service.record_outcome(issue, NODE)
    assert set(result) == {"issue", "team", "already_learned", "predicted", "correct", "links_reweighted", "shortcuts_created", "merges"}
    assert result["team"] == NODE and result["issue"] == issue.number and not result["already_learned"]
    assert offline.state.counters["issues_learned"] == before + 1
    assert service.LIVE_STATE_FILE.exists()
    with pytest.raises(ValueError):
        service.record_outcome(issue, "sig/not-a-team")


def test_record_outcome_on_a_learned_issue_changes_nothing(offline):
    saved = json.dumps(offline.state.to_json(), sort_keys=True)
    for issue in ISSUES:
        assert service.record_outcome(issue, NODE) == {"team": NODE, "issue": issue.number, "already_learned": True}
    assert json.dumps(offline.state.to_json(), sort_keys=True) == saved
    assert not service.LIVE_STATE_FILE.exists()


def test_route_as_of_scores_against_a_snapshot(offline, monkeypatch):
    monkeypatch.setattr(service, "snapshot", lambda as_of: offline.state)
    result = service.route_issue("kubelet oom", "", "", as_of=1700)
    assert result.top_team == NODE and result.teams[0].path[-1] == NODE


def test_stats_reads_graph_counts_once_until_a_learning_step(offline, monkeypatch):
    calls = []
    monkeypatch.setattr(service.db, "counts", lambda: calls.append(1) or {"nodes": {"Team": 1, "Entity": 2, "Issue": 3}, "links": {"ROUTES_TO": 4}})
    service.graph_counts.cache_clear()
    assert service.stats()["nodes"] == 6
    service.stats()
    assert len(calls) == 1
    service.record_outcome(replace(ISSUES[0], number=ISSUES[0].number + 20_000), NODE)
    service.stats()
    assert len(calls) == 2
    service.graph_counts.cache_clear()
