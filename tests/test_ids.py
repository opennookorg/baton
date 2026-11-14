import pytest

from baton.config import ENTITY_ID_BASE, ISSUE_ID_BASE, TEAM_ID_BASE
from baton.ids import IdTable, build_table


def test_build_is_stable_regardless_of_input_order():
    first = build_table(["sig/node", "sig/apps", "sig/node"], ["word:b", "comp:a"])
    second = build_table(["sig/apps", "sig/node"], ["comp:a", "word:b"])
    assert first.teams == second.teams == {"sig/apps": TEAM_ID_BASE, "sig/node": TEAM_ID_BASE + 1}
    assert first.entities == second.entities == {"comp:a": ENTITY_ID_BASE, "word:b": ENTITY_ID_BASE + 1}


def test_save_load_round_trip_and_append(tmp_path):
    table = build_table(["sig/node"], ["comp:kubelet"])
    path = tmp_path / "ids.json"
    table.save(path)
    loaded = IdTable.load(path)
    assert loaded.teams == table.teams and loaded.entities == table.entities
    assert loaded.add_entity("comp:kubelet") == ENTITY_ID_BASE
    assert loaded.add_entity("word:new") == ENTITY_ID_BASE + 1
    assert loaded.add_team("sig/apps") == TEAM_ID_BASE + 1
    assert loaded.name_of(ENTITY_ID_BASE + 1) == "word:new"


def test_lookups_and_issue_ids():
    table = build_table(["sig/node"], ["comp:kubelet"])
    assert table.team_id("sig/node") == TEAM_ID_BASE
    assert table.entity_id("comp:missing") is None
    assert IdTable.issue_id(1234) == ISSUE_ID_BASE + 1234
    assert table.name_of(ISSUE_ID_BASE + 1234) == "#1234"
    with pytest.raises(KeyError):
        table.team_id("sig/unknown")


def test_team_range_is_enforced():
    table = IdTable({"sig/x": 999})
    with pytest.raises(ValueError):
        table.add_team("sig/y")
