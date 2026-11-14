from dataclasses import replace

import pytest

from baton import db
from baton.config import LearnParams, Techniques
from baton.dataset import load_issues, load_reserve
from baton.ids import IdTable
from baton.learn import Learner
from baton.passes import ReservePool, compound_name, merge_pairs, split_pass, with_compounds
from baton.snapshots import GraphState, Link, PastIssue
from tests.test_db import node_listening
from tests.test_router import ISSUES, NET, make_issue, small_table

ALL = Techniques(reweight=True, shortcuts=True, merging=True, splitting=True, gap_filling=True)
LOOSE = LearnParams(
    merge_similarity=0.9,
    merge_min_hits=1,
    split_min_misses=1,
    split_dominance=1.0,
    split_min_support=1,
    gap_confidence=1.01,
    gap_min_known=100,
    gap_pull=3,
    shortcut_min_paths=3,
    history_keep=1,
)
FLANNEL = make_issue(5, "flannel overlay drops packets", "flannel vxlan on kube-proxy", NET)
RESERVE = [
    replace(make_issue(10 + k, f"flannel overlay {word}", "flannel vxlan", NET), created_at="2023-01-0{}T00:00:00Z".format(k + 1))
    for k, word in enumerate(("broken", "slow", "flaps"))
]


class GrowingTable(IdTable):
    """An IdTable whose new entities take the next ID inside the test range."""

    def add_entity(self, name: str) -> int:
        """Return the entity's ID, assigning the next test-range one if it is new."""
        if name not in self.entities:
            self.entities[name] = self.next_entity_id
            self.names_by_id[self.next_entity_id] = name
            self.next_entity_id += 1
        return self.entities[name]


def growing_table() -> GrowingTable:
    """The router tests' small table, able to grow inside the test ID range."""
    table = small_table()
    return GrowingTable(table.teams, table.entities)


def state_with(issues: list[tuple[list[str], list[str]]]) -> GraphState:
    """A GraphState holding (entities, teams) issues as history, with the counts the learner keeps."""
    state = GraphState()
    for number, (entities, teams) in enumerate(issues, 1):
        state.add_issue(number, PastIssue("", entities, teams))
        for entity in entities:
            state.entity_issues[entity] += 1
            for team in teams:
                state.history_paths[(entity, team)] += 1
    return state


def test_compounds_appear_only_when_every_part_is_present():
    name = compound_name("word:timeout", "comp:kubelet")
    assert name == "comp:kubelet+word:timeout"
    assert with_compounds(["comp:kubelet", "word:timeout"], [name, "comp:pod"]) == ["comp:kubelet", "word:timeout", name]
    assert with_compounds(["comp:kubelet"], [name]) == ["comp:kubelet"]


def test_merge_pairs_links_same_kind_entities_with_matching_profiles():
    state = state_with([(["word:a", "word:b", "comp:c"], ["t1"])] * 2 + [(["word:d"], ["t2"])] * 2)
    params = LearnParams(merge_similarity=0.99, merge_min_hits=2)
    assert merge_pairs(state, params) == [("word:a", "word:b")]
    state.add_same_as("word:a", "word:b")
    assert merge_pairs(state, params) == []
    assert merge_pairs(state, replace(params, merge_min_hits=3)) == []


def test_split_pass_pairs_an_ambiguous_entity_with_its_most_informative_partner():
    state = state_with([(["comp:a", "word:x"], ["t1"])] * 2 + [(["comp:a", "word:y"], ["t2"])] * 2)
    state.entity_misses["comp:a"] = 5
    params = LearnParams(split_min_misses=5, split_dominance=0.5, split_min_support=2)
    assert split_pass(state, set(), params) == {"comp:a+word:x": {"t1": Link(params.shortcut_scale, hits=2)}}
    assert split_pass(state, {"comp:a+word:x"}, params) == {"comp:a+word:y": {"t2": Link(params.shortcut_scale, hits=2)}}
    assert split_pass(state, set(), replace(params, split_dominance=0.4)) == {}
    assert split_pass(state, set(), replace(params, split_min_misses=6)) == {}


def test_reserve_pull_takes_only_older_issues_not_yet_in_history():
    pool = ReservePool.build(RESERVE)
    state = GraphState()
    assert pool.pull(FLANNEL, ["word:flannel"], state, 2) == [2, 1]
    state.add_issue(RESERVE[2].number, PastIssue("", [], []))
    assert pool.pull(FLANNEL, ["word:flannel"], state, 5) == [1, 0]
    assert pool.pull(replace(FLANNEL, created_at="2023-01-02T00:00:00Z"), ["word:flannel"], GraphState(), 5) == [0]
    assert pool.vocabulary([0, 1, 2], ["word:flannel", "word:packet"]) == ["word:flannel"]


def test_reserve_is_older_than_and_disjoint_from_the_main_issues():
    reserve, main = load_reserve(), load_issues()
    assert max(i.created_at for i in reserve) < min(i.created_at for i in main)
    assert not {i.number for i in reserve} & {i.number for i in main}


@pytest.fixture
def passes_graph():
    if not node_listening():
        pytest.skip("no HydraDB listening on 127.0.0.1:7687")
    table = growing_table()
    issue_ids = [table.issue_id(i.number) for i in [*ISSUES, FLANNEL, *RESERVE]]
    db.delete_nodes([*table.teams.values(), *table.entities.values(), *issue_ids])
    db.upsert_teams((i, n) for n, i in table.teams.items())
    db.upsert_entities((i, n, n.split(":")[0]) for n, i in table.entities.items())
    yield table
    db.delete_nodes([*table.teams.values(), *table.entities.values(), *issue_ids])
    db.close()


def test_live_passes_match_the_offline_mirror(passes_graph):
    live_table, offline_table = passes_graph, growing_table()
    pool = ReservePool.build(RESERVE)
    live = Learner(live_table, ALL, LOOSE, reserve=pool)
    offline = Learner(offline_table, ALL, LOOSE, live=False, reserve=pool)
    for issue in [*ISSUES, FLANNEL]:
        assert live.learn(issue) == offline.learn(issue)
    assert live.end_batch() == offline.end_batch()
    state = offline.state
    assert state.counters["gap_issues"] > 0 and state.counters["merges"] > 0 and state.counters["splits"] > 0
    assert "word:flannel" in state.added_entities
    assert live.state.to_json() == state.to_json()
    assert live_table.entities == offline_table.entities
    rows = db.routes_from_entities(live_table.entities.values())
    names = live_table.names_by_id
    assert {(names[r["entity"]], names[r["team"]]): r["strength"] for r in rows} == {p: k.strength for p, k in state.routes.items()}
    same_as = db.read("MATCH (a:Entity)-[:SAME_AS]->(b:Entity) WHERE a.id >= 900000000 RETURN a.id AS a, b.id AS b")
    assert {(names[r["a"]], names[r["b"]]) for r in same_as} == state.same_as
    issues = db.read("MATCH (i:Issue) WHERE i.id >= 900000000 RETURN i.number AS n")
    assert sorted(row["n"] for row in issues) == sorted(state.history)
    assert live.route(FLANNEL).result == offline.route(FLANNEL).result
