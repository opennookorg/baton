from baton.ingest import issue_row
from baton.learn import Learner
from eval.restore_graph import graph_rows
from tests.test_learn import LEARNED, PARAMS
from tests.test_router import ISSUES, small_table


def test_graph_rows_hold_exactly_the_learned_state():
    table = small_table()
    learner = Learner(table, LEARNED, PARAMS, live=False)
    for issue in ISSUES:
        learner.learn(issue)
    learner.end_batch()
    state = learner.state
    state.add_same_as(*sorted(table.entities)[:2])
    issues, routes, same_as = graph_rows(state, table)
    assert [row["number"] for row in issues] == sorted(state.history)
    first = issues[0]
    past = state.history[first["number"]]
    assert first["entities"] == [table.entity_id(name) for name in past.entities]
    assert first["teams"] == [table.team_id(team) for team in past.teams]
    assert len(routes) == len(state.routes) and all(row["cost"] == 1 / row["strength"] for row in routes)
    names = table.names_by_id
    assert {(names[a], names[b]) for a, b in same_as} | {(names[b], names[a]) for a, b in same_as} == state.same_as
    assert set(first) == set(issue_row(ISSUES[0], table, [], []))
