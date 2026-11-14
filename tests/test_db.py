import socket

import pytest

from baton import db

BASE = 900_000_000
TEAM_CHEAP = BASE + 1
TEAM_SHORT = BASE + 2
ENTITY_A = BASE + 10
ENTITY_B = BASE + 11
ISSUE = BASE + 100
ALL_IDS = (TEAM_CHEAP, TEAM_SHORT, ENTITY_A, ENTITY_B, ISSUE)
PREFIX = "zz-test-"


def node_listening(host: str = "127.0.0.1", port: int = 7687) -> bool:
    """Return True when something accepts TCP connections on the Bolt port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def route(entity: int, team: int, strength: float, hits: int = 0, misses: int = 0) -> dict:
    """Build one ROUTES_TO row."""
    return {"entity": entity, "team": team, "strength": strength, "cost": 1 / strength, "hits": hits, "misses": misses}


@pytest.fixture
def graph():
    if not node_listening():
        pytest.skip("no HydraDB listening on 127.0.0.1:7687")
    db.delete_nodes(ALL_IDS)
    db.upsert_teams([(TEAM_CHEAP, PREFIX + "cheap"), (TEAM_SHORT, PREFIX + "short")])
    db.upsert_entities([(ENTITY_A, PREFIX + "o'brien\\a", "word"), (ENTITY_B, PREFIX + "b", "component")])
    yield
    db.delete_nodes(ALL_IDS)
    db.close()


def test_routes_upsert_is_idempotent_and_updates(graph):
    db.upsert_routes([route(ENTITY_A, TEAM_SHORT, 0.5), route(ENTITY_A, TEAM_SHORT, 0.5)])
    db.upsert_routes([route(ENTITY_A, TEAM_SHORT, 0.5)])
    db.upsert_routes([route(ENTITY_A, TEAM_SHORT, 2.0, hits=3, misses=1)])
    links = db.routes_from_entities([ENTITY_A])
    assert links == [{"entity": ENTITY_A, "team": TEAM_SHORT, "strength": 2.0, "cost": 0.5, "hits": 3, "misses": 1, "shortcut": False}]
    assert db.routes_to_team(TEAM_SHORT) == links


def test_issue_writes_links_and_delete_removes_them(graph):
    issue = {"id": ISSUE, "number": 100, "title": "kubelet oom", "team": TEAM_CHEAP, "entities": [ENTITY_A, ENTITY_B]}
    db.upsert_issues([issue])
    db.upsert_issues([issue])
    seen = db.read("MATCH (e:Entity)-[r:SEEN_IN]->(i:Issue {id: $id}) RETURN e.id AS e, r.cost AS cost", id=ISSUE)
    assert sorted(row["e"] for row in seen) == [ENTITY_A, ENTITY_B]
    owned = db.read("MATCH (i:Issue {id: $id})-[r:OWNED_BY]->(t) RETURN t.id AS t, r.cost AS cost", id=ISSUE)
    assert owned == [{"t": TEAM_CHEAP, "cost": 1.0}]
    db.delete_issues([ISSUE])
    assert db.read("MATCH (i:Issue {id: $id}) RETURN i.id AS id", id=ISSUE) == []
    assert db.read("MATCH (e:Entity {id: $id})-[:SEEN_IN]->(i) RETURN i.id AS id", id=ENTITY_A) == []


def test_same_as_written_both_ways(graph):
    db.upsert_same_as([(ENTITY_A, ENTITY_B)])
    db.upsert_same_as([(ENTITY_A, ENTITY_B)])
    forward = db.read("MATCH (a:Entity {id: $id})-[r:SAME_AS]->(b) RETURN b.id AS b, r.cost AS cost", id=ENTITY_A)
    back = db.read("MATCH (a:Entity {id: $id})-[r:SAME_AS]->(b) RETURN b.id AS b, r.cost AS cost", id=ENTITY_B)
    assert forward == [{"b": ENTITY_B, "cost": 0.1}]
    assert back == [{"b": ENTITY_A, "cost": 0.1}]


def test_ms_paths_prefers_cheap_path_over_short_one(graph):
    db.upsert_routes([route(ENTITY_A, TEAM_SHORT, 0.2), route(ENTITY_A, TEAM_CHEAP, 0.2)])
    db.upsert_issues([{"id": ISSUE, "number": 100, "title": "t", "team": TEAM_CHEAP, "entities": [ENTITY_A]}])
    paths = db.ms_paths([PREFIX + "o'brien\\a"], [PREFIX + "cheap", PREFIX + "short"], path_count=1)
    by_team = {path["nodes"][-1]: path for path in paths}
    assert by_team[PREFIX + "cheap"]["rels"] == ["SEEN_IN", "OWNED_BY"]
    assert by_team[PREFIX + "cheap"]["weight"] == pytest.approx(2.0)
    assert by_team[PREFIX + "cheap"]["nodes"] == [PREFIX + "o'brien\\a", "#100", PREFIX + "cheap"]
    assert by_team[PREFIX + "short"]["rels"] == ["ROUTES_TO"]
    assert by_team[PREFIX + "short"]["weight"] == pytest.approx(5.0)


def test_ms_paths_unknown_names_return_nothing(graph):
    assert db.ms_paths([PREFIX + "missing"], [PREFIX + "cheap"]) == []
    assert db.ms_paths([], [PREFIX + "cheap"]) == []


def test_counts_include_written_nodes(graph):
    before = db.counts()
    db.upsert_routes([route(ENTITY_B, TEAM_SHORT, 1.0)])
    after = db.counts()
    assert after["nodes"]["Team"] >= 2
    assert after["links"]["ROUTES_TO"] == before["links"]["ROUTES_TO"] + 1


def test_cypher_strings_escapes_backslash_before_quote():
    assert db.cypher_strings(["plain", "o'brien", "back\\slash", "evil\\'quote"]) == (
        "['plain', 'o\\'brien', 'back\\\\slash', 'evil\\\\\\'quote']"
    )


def test_link_ids_are_unique_per_type_and_direction():
    ids = {db.link_id(rel, a, b) for rel in db.PATH_REL_TYPES for a, b in ((1, 2), (2, 1), (100_000, 1))}
    assert len(ids) == 12
    with pytest.raises(ValueError):
        db.link_id("ROUTES_TO", db.NODE_ID_LIMIT, 1)
