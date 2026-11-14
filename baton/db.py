"""HydraDB access: cached driver, batched MERGE writers, readers and the algo.MSpaths wrapper."""

from collections.abc import Iterable, Sequence
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from baton.config import HISTORY_COST, HYDRADB_DATABASE, HYDRADB_TOKEN, HYDRADB_URI, SAME_AS_COST

CHUNK_SIZE = 1000
LABELS = ("Team", "Entity", "Issue")
LINK_SOURCES = {"ROUTES_TO": "Entity", "SEEN_IN": "Entity", "OWNED_BY": "Issue", "SAME_AS": "Entity"}
PATH_REL_TYPES = ("ROUTES_TO", "SEEN_IN", "OWNED_BY", "SAME_AS")
LINK_TYPE_CODES = {rel: code for code, rel in enumerate(PATH_REL_TYPES)}
NODE_ID_LIMIT = 1_000_000_000

UPSERT_TEAMS = "UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Team, n.name = row.name"
UPSERT_ENTITIES = "UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Entity, n.name = row.name, n.kind = row.kind"
UPSERT_ISSUE_NODES = "UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Issue, n.number = row.number, n.title = row.title"
UPSERT_SEEN_IN = (
    "UNWIND $rows AS row MATCH (e:Entity {id: row.entity}), (i:Issue {id: row.issue}) "
    "MERGE (e)-[r:SEEN_IN {id: row.rid}]->(i) SET r.cost = row.cost"
)
UPSERT_OWNED_BY = (
    "UNWIND $rows AS row MATCH (i:Issue {id: row.issue}), (t:Team {id: row.team}) "
    "MERGE (i)-[r:OWNED_BY {id: row.rid}]->(t) SET r.cost = row.cost"
)
UPSERT_ROUTES = (
    "UNWIND $rows AS row MATCH (e:Entity {id: row.entity}), (t:Team {id: row.team}) "
    "MERGE (e)-[r:ROUTES_TO {id: row.rid}]->(t) "
    "SET r.strength = row.strength, r.cost = row.cost, r.hits = row.hits, r.misses = row.misses"
)
UPSERT_SAME_AS = (
    "UNWIND $rows AS row MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b}) "
    "MERGE (a)-[r:SAME_AS {id: row.rid}]->(b) SET r.cost = row.cost"
)
DELETE_BY_ID = "UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n"
ROUTE_COLUMNS = (
    "e.id AS entity, t.id AS team, r.strength AS strength, r.cost AS cost, r.hits AS hits, r.misses AS misses"
)


@lru_cache(maxsize=1)
def driver() -> Driver:
    """Return the process-wide HydraDB driver."""
    return GraphDatabase.driver(HYDRADB_URI, auth=("neo4j", HYDRADB_TOKEN))


def close() -> None:
    """Close the cached driver, if one was opened."""
    if driver.cache_info().currsize:
        driver().close()
        driver.cache_clear()


def run(query: str, **params) -> None:
    """Run one auto-commit write statement."""
    with driver().session(database=HYDRADB_DATABASE) as session:
        session.run(query, **params).consume()


def read(query: str, **params) -> list[dict]:
    """Run one read statement and return its rows as dicts."""
    with driver().session(database=HYDRADB_DATABASE) as session:
        return [record.data() for record in session.run(query, **params)]


def write_rows(query: str, rows: Iterable[dict], chunk_size: int = CHUNK_SIZE) -> int:
    """Run an UNWIND $rows statement in chunks under the 1024-item batch cap; return rows written."""
    rows = list(rows)
    with driver().session(database=HYDRADB_DATABASE) as session:
        for start in range(0, len(rows), chunk_size):
            session.run(query, rows=rows[start : start + chunk_size]).consume()
    return len(rows)


def link_id(rel: str, source: int, target: int) -> int:
    """Return the deterministic, graph-wide unique id HydraDB needs to MERGE one link."""
    if not (0 <= source < NODE_ID_LIMIT and 0 <= target < NODE_ID_LIMIT):
        raise ValueError(f"node ids must be in [0, {NODE_ID_LIMIT}) to build a link id: {source}, {target}")
    return (source * NODE_ID_LIMIT + target) * len(LINK_TYPE_CODES) + LINK_TYPE_CODES[rel]


def write_links(query: str, rel: str, rows: Iterable[dict], source: str, target: str) -> int:
    """Attach a rid to each link row, drop duplicates within the batch, and write them."""
    unique = {link_id(rel, row[source], row[target]): row for row in rows}
    return write_rows(query, ({**row, "rid": rid} for rid, row in unique.items()))


def upsert_teams(teams: Iterable[tuple[int, str]]) -> int:
    """MERGE Team nodes from (id, name) pairs."""
    return write_rows(UPSERT_TEAMS, ({"id": team_id, "name": name} for team_id, name in teams))


def upsert_entities(entities: Iterable[tuple[int, str, str]]) -> int:
    """MERGE Entity nodes from (id, name, kind) triples."""
    return write_rows(UPSERT_ENTITIES, ({"id": i, "name": name, "kind": kind} for i, name, kind in entities))


def upsert_issues(issues: Iterable[dict]) -> int:
    """MERGE Issue nodes from {id, number, title, team, entities}, with SEEN_IN and OWNED_BY links."""
    issues = list(issues)
    write_rows(UPSERT_ISSUE_NODES, ({"id": i["id"], "number": i["number"], "title": i["title"]} for i in issues))
    seen_in = ({"entity": e, "issue": i["id"], "cost": HISTORY_COST} for i in issues for e in i["entities"])
    write_links(UPSERT_SEEN_IN, "SEEN_IN", seen_in, "entity", "issue")
    owned_by = ({"issue": i["id"], "team": i["team"], "cost": HISTORY_COST} for i in issues)
    write_links(UPSERT_OWNED_BY, "OWNED_BY", owned_by, "issue", "team")
    return len(issues)


def upsert_routes(routes: Iterable[dict]) -> int:
    """MERGE ROUTES_TO links from {entity, team, strength, cost, hits, misses}."""
    return write_links(UPSERT_ROUTES, "ROUTES_TO", routes, "entity", "team")


def upsert_same_as(pairs: Iterable[tuple[int, int]]) -> int:
    """MERGE SAME_AS links both ways for each (a, b) entity pair."""
    rows = [{"a": x, "b": y, "cost": SAME_AS_COST} for a, b in pairs for x, y in ((a, b), (b, a))]
    return write_links(UPSERT_SAME_AS, "SAME_AS", rows, "a", "b")


def routes_from_entities(entity_ids: Iterable[int]) -> list[dict]:
    """Return ROUTES_TO links leaving the given entities."""
    query = f"MATCH (e:Entity {{id: $id}})-[r:ROUTES_TO]->(t) RETURN {ROUTE_COLUMNS}"
    with driver().session(database=HYDRADB_DATABASE) as session:
        return [record.data() for entity_id in entity_ids for record in session.run(query, id=entity_id)]


def routes_to_team(team_id: int) -> list[dict]:
    """Return ROUTES_TO links arriving at one team."""
    return read(f"MATCH (e:Entity)-[r:ROUTES_TO]->(t:Team {{id: $id}}) RETURN {ROUTE_COLUMNS}", id=team_id)


def all_routes() -> list[dict]:
    """Return every ROUTES_TO link in the graph."""
    return read(f"MATCH (e:Entity)-[r:ROUTES_TO]->(t) RETURN {ROUTE_COLUMNS}")


def delete_nodes(node_ids: Iterable[int]) -> int:
    """DETACH DELETE nodes by id, in chunks."""
    return write_rows(DELETE_BY_ID, ({"id": node_id} for node_id in node_ids))


def delete_issues(issue_ids: Iterable[int]) -> int:
    """Delete Issue nodes and their SEEN_IN and OWNED_BY links."""
    return delete_nodes(issue_ids)


def node_ids(label: str) -> list[int]:
    """Return the ids of every node with a label."""
    return [row["id"] for row in read(f"MATCH (n:{label}) RETURN n.id AS id")]


def reset() -> None:
    """Delete every Team, Entity and Issue node and all their links."""
    for label in LABELS:
        while ids := node_ids(label):
            delete_nodes(ids)


def counts() -> dict:
    """Return {"nodes": {label: n}, "links": {type: n}}."""
    nodes = {label: read(f"MATCH (n:{label}) RETURN count(*) AS n")[0]["n"] for label in LABELS}
    links = {
        rel: read(f"MATCH (a:{source})-[:{rel}]->(b) RETURN count(*) AS n")[0]["n"]
        for rel, source in LINK_SOURCES.items()
    }
    return {"nodes": nodes, "links": links}


def cypher_strings(values: Iterable[str]) -> str:
    """Render strings as a Cypher list literal, escaping backslashes before quotes."""
    escaped = (value.replace("\\", "\\\\").replace("'", "\\'") for value in values)
    return "[" + ", ".join(f"'{value}'" for value in escaped) + "]"


def ms_paths_query(
    sources: Sequence[str], targets: Sequence[str], max_len: int = 3, path_count: int = 3, result_limit: int = 500
) -> str:
    """Build the weighted algo.MSpaths query text from entity names to team names."""
    return (
        "CALL algo.MSpaths({"
        f"sourceLabel: 'Entity', sourceProperty: 'name', sourceValues: {cypher_strings(sources)}, "
        f"targetLabel: 'Team', targetProperty: 'name', targetValues: {cypher_strings(targets)}, "
        f"relTypes: {cypher_strings(PATH_REL_TYPES)}, relDirection: 'outgoing', "
        f"maxLen: {int(max_len)}, pathCount: {int(path_count)}, pairwise: false, "
        f"weightProp: 'cost', resultLimit: {int(result_limit)}"
        "}) YIELD path, pathWeight RETURN path, pathWeight"
    )


def node_display_name(node) -> str:
    """Name a path node: its name, or #number for an Issue."""
    if "name" in node:
        return node["name"]
    return f"#{node['number']}" if "number" in node else node.element_id


def ms_paths(
    sources: Sequence[str], targets: Sequence[str], max_len: int = 3, path_count: int = 3, result_limit: int = 500
) -> list[dict]:
    """Run weighted algo.MSpaths and return [{nodes, ids, rels, weight}] as plain Python data."""
    if not sources or not targets:
        return []
    query = ms_paths_query(sources, targets, max_len, path_count, result_limit)
    with driver().session(database=HYDRADB_DATABASE) as session:
        records = list(session.run(query))
    return [
        {
            "nodes": [node_display_name(node) for node in record["path"].nodes],
            "ids": [int(node.element_id) for node in record["path"].nodes],
            "rels": [rel.type for rel in record["path"].relationships],
            "weight": float(record["pathWeight"]),
        }
        for record in records
    ]
