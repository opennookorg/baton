import pytest

from baton import db
from baton.entities import extract
from baton.ids import IdTable
from baton.ingest import ingest_history, issue_entities, issue_teams
from baton.models import Issue
from baton.router import cheapest_per_pair, display_name, rank, route_live, route_state
from baton.snapshots import GraphState, Link, PastIssue
from tests.test_db import node_listening

BASE = 900_000_000
NODE, NET = "zz-test-node", "zz-test-net"
ISSUE_NUMBER_BASE = BASE - 1_000_000 + 500


def make_issue(n: int, title: str, body: str, sig: str) -> Issue:
    """A test issue with a number whose node ID lands in the test range."""
    return Issue(ISSUE_NUMBER_BASE + n, title, body, "2024-01-01T00:00:00Z", "zz-test-alice", (sig,))


ISSUES = [
    make_issue(1, "kubelet oom killed pod", "kubelet crashes in pkg/kubelet/cm", NODE),
    make_issue(2, "kubelet restarts pod", "pod restarted by kubelet", NODE),
    make_issue(3, "service dns lookup fails", "kube-proxy drops dns for the service", NET),
    make_issue(4, "pod cannot reach service", "kube-proxy rules missing for pod", NET),
]


def small_table() -> IdTable:
    """Teams and every entity the test issues extract to, inside the test ID range."""
    names = sorted({e.name for i in ISSUES for e in extract(i.title, i.body, i.reporter)})
    return IdTable({NODE: BASE + 1, NET: BASE + 2}, {name: BASE + 10 + k for k, name in enumerate(names)})


def history_state(table: IdTable) -> GraphState:
    """A GraphState holding the test issues as history."""
    state = GraphState()
    for issue in ISSUES:
        state.add_issue(issue.number, PastIssue(issue.title, issue_entities(issue, table), issue_teams(issue, table)))
    return state


def path(nodes: list[str], weight: float) -> dict:
    return {"nodes": nodes, "rels": ["ROUTES_TO"] * (len(nodes) - 1), "weight": weight}


def test_rank_sums_inverse_weights_split_across_the_teams_each_entity_reaches():
    routed = rank([path(["word:a", "t1"], 0.5), path(["word:b", "t1"], 2.0), path(["word:a", "t2"], 1.0)], 2, 1)
    result = routed.result
    assert [t.team for t in result.teams] == ["t1", "t2"]
    assert result.teams[0].share == round((2 / 2 + 0.5) / (2 / 2 + 0.5 + 1 / 2), 3)
    assert result.teams[0].path == ["a", "t1"]
    assert result.confidence == result.teams[0].share
    assert (result.entities_found, result.entities_unknown) == (2, 1)


def test_rank_discounts_an_entity_that_reaches_every_team():
    generic = [path(["word:pod", team], 0.5) for team in ("t1", "t2", "t3", "t4")]
    routed = rank(generic + [path(["word:scheduler", "t2"], 1.0)], 2, 0)
    assert routed.result.top_team == "t2"
    assert routed.result.teams[0].share == round(1.5 / 3.0, 3)


def test_rank_with_no_paths_returns_no_teams():
    result = rank([], 0, 3).result
    assert result.teams == [] and result.confidence == 0.0 and result.top_team is None


def test_cheapest_per_pair_keeps_cheapest_and_skips_the_issue_itself():
    paths = [path(["word:a", f"#{n}", "t"], float(n)) for n in (1, 2, 3, 4)]
    kept = cheapest_per_pair(paths, path_count=3, exclude_issue=1)
    assert [p["nodes"][1] for p in kept] == ["#2", "#3", "#4"]


def test_route_state_uses_history_and_shortcuts():
    table = small_table()
    state = history_state(table)
    assert route_state(state, "kubelet oom", "", "", table).result.top_team == NODE
    assert route_state(state, "kube-proxy dns", "", "", table).result.top_team == NET
    state.set_link(("comp:kubelet", NET), Link(100.0, shortcut=True))
    assert route_state(state, "kubelet oom", "", "", table).result.top_team == NET


@pytest.fixture
def live_graph():
    if not node_listening():
        pytest.skip("no HydraDB listening on 127.0.0.1:7687")
    table = small_table()
    ids = [*table.teams.values(), *table.entities.values(), *(table.issue_id(i.number) for i in ISSUES)]
    db.delete_nodes(ids)
    db.upsert_teams((i, n) for n, i in table.teams.items())
    db.upsert_entities((i, n, n.split(":")[0]) for n, i in table.entities.items())
    yield table
    db.delete_nodes(ids)
    db.close()


def test_live_and_pure_routers_agree(live_graph):
    table = live_graph
    ingest_history(ISSUES, table)
    state = history_state(table)
    for issue in ISSUES:
        live = route_live(issue.title, issue.body, issue.reporter, table, issue.number).result
        pure = route_state(state, issue.title, issue.body, issue.reporter, table, issue.number).result
        assert live == pure


def test_display_name_strips_entity_kinds_but_keeps_team_names_with_colons():
    assert display_name("path:pkg/kubelet") == "pkg/kubelet"
    assert display_name("Component: DOM") == "Component: DOM"
    assert display_name("sig/node") == "sig/node"
