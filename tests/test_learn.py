import pytest

from baton import db
from baton.config import BATON, COUNT_ONLY, LearnParams, Techniques
from baton.learn import Learner, check_techniques, prunable, reweight, shortcut_pass
from baton.snapshots import GraphState, Link, PastIssue
from tests.test_router import ISSUES, NET, NODE, live_graph, small_table

PARAMS = LearnParams(reward=0.5, penalty=0.5, floor=0.2, shortcut_min_paths=3, history_keep=1)
LEARNED = Techniques(reweight=True, shortcuts=True, merging=False, splitting=False, gap_filling=False)
__all__ = ["live_graph"]


def test_right_answer_rewards_only_the_winning_links():
    links = {("a", "t1"): Link(1.0), ("b", "t1"): Link(1.0)}
    changed = reweight(links, ["a", "b"], ["t1"], "t1", {("a", "t1")}, PARAMS)
    assert changed == {("a", "t1"): Link(1.5, hits=1)}


def test_wrong_answer_penalises_with_floor_and_creates_the_real_link():
    links = {("a", "wrong"): Link(0.3), ("a", "right"): Link(1.0)}
    changed = reweight(links, ["a", "b"], ["right"], "wrong", set(), PARAMS)
    assert changed == {
        ("a", "wrong"): Link(0.2, misses=1),
        ("a", "right"): Link(1.5, hits=1),
        ("b", "right"): Link(0.5, hits=1),
    }


def test_shortcut_strength_is_the_scaled_team_share_and_updates_by_difference():
    state = GraphState()
    state.history_paths.update({("a", "t1"): 3, ("a", "t2"): 1})
    state.entity_issues["a"] = 4
    changed, absorbed = shortcut_pass(state, PARAMS)
    assert changed == {("a", "t1"): Link(LearnParams().shortcut_scale * 3 / 4, shortcut=True)}
    for pair, link in changed.items():
        state.set_link(pair, link)
    state.absorbed.update(absorbed)
    assert shortcut_pass(state, PARAMS) == ({}, {})
    state.set_link(("a", "t1"), Link(state.routes[("a", "t1")].strength + 1.0, hits=1, shortcut=True))
    state.history_paths[("a", "t1")] = 4
    state.entity_issues["a"] = 5
    changed, _ = shortcut_pass(state, PARAMS)
    assert changed[("a", "t1")].strength == pytest.approx(1.0 + LearnParams().shortcut_scale * 4 / 5)
    assert changed[("a", "t1")].hits == 1


def test_prune_keeps_recent_issues_and_issues_not_covered_by_links():
    state = GraphState()
    for number, entities in ((1, ["a"]), (2, ["b"]), (3, ["a"])):
        state.add_issue(number, PastIssue("", entities, ["t"]))
        state.learned_order.append(number)
    state.set_link(("a", "t"), Link(1.0))
    assert prunable(state, keep=1) == [1]


def test_unimplemented_techniques_are_refused():
    with pytest.raises(ValueError, match="merging"):
        check_techniques(BATON)
    check_techniques(LEARNED)


def test_offline_learner_counts_and_learns_a_misroute():
    table = small_table()
    learner = Learner(table, LEARNED, PARAMS, live=False)
    outcomes = [learner.learn(issue) for issue in ISSUES]
    counters = learner.state.counters
    assert counters["issues_learned"] == 4
    assert counters["misroutes"] == sum(not o["correct"] for o in outcomes)
    assert counters["links_reweighted"] == sum(o["links_reweighted"] for o in outcomes)
    assert learner.route(ISSUES[0]).result.top_team == NODE
    assert learner.route(ISSUES[2]).result.top_team == NET


def test_count_only_learner_writes_history_without_links():
    learner = Learner(small_table(), COUNT_ONLY, PARAMS, live=False)
    for issue in ISSUES:
        learner.learn(issue)
    assert learner.state.routes == {} and len(learner.state.history) == 4


def test_live_learner_matches_the_offline_mirror(live_graph):
    table = live_graph
    live, offline = Learner(table, LEARNED, PARAMS), Learner(table, LEARNED, PARAMS, live=False)
    for issue in ISSUES:
        assert live.learn(issue) == offline.learn(issue)
    live.end_batch()
    offline.end_batch()
    assert live.state.to_json() == offline.state.to_json()
    rows = db.routes_from_entities(table.entities.values())
    assert {(table.names_by_id[r["entity"]], table.names_by_id[r["team"]]): r["strength"] for r in rows} == {
        pair: link.strength for pair, link in offline.state.routes.items()
    }
    issues = db.read("MATCH (i:Issue) WHERE i.id >= 900000000 RETURN i.number AS n")
    assert sorted(row["n"] for row in issues) == sorted(offline.state.history)
