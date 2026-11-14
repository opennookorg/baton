# HydraDB notes

Findings from building and probing a local HydraDB node for Baton. Everything below was run against the live node, not copied from docs.

## Build and start

- Checkout: `~/Projects/hydradb` at `9166374`. Override with `BATON_HYDRADB_HOME`.
- Toolchain: `rust-toolchain.toml` pins Rust 1.99.0. Homebrew `rustc` 1.92 is too old, so install rustup (`~/.cargo/bin`); `scripts/start_hydradb.sh` prefers `~/.cargo/bin/cargo`.
- macOS needs Homebrew `suite-sparse`, `libcypher-parser` (from `cleishm/neo4j`) and `just`, plus `BINDGEN_EXTRA_CLANG_ARGS="-I$(brew --prefix)/include"` and `LIBRARY_PATH="$(brew --prefix)/lib"`. The script sets both.
- First build of `cargo run --locked --features server-runtime --bin graph-node` takes several minutes. Later starts reuse the build.
- `scripts/start_hydradb.sh` runs in the foreground; `--background` uses nohup, logs to `.hydradb/node.log`, writes `.hydradb/node.pid` and waits for port 7687; `stop` stops it. Both are idempotent.
- The spec smoke check prints `999998`.

## Connecting

- Bolt `bolt://127.0.0.1:7687`, user `neo4j`, password is the token, database `default`. HTTP health on `127.0.0.1:8443/healthz`.
- Auto-commit only. `BEGIN` is rejected, so use `session.run`, never `execute_write` or `execute_query`.

## Writing

- Node batches: `UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Label, n.prop = row.prop`. Set exactly one label, first.
- Batches are capped at 1024 items. `db.write_rows` chunks to 1000.
- **Link MERGE needs an id.** `MERGE (a)-[r:TYPE]->(b)` inside `UNWIND` is rejected. Write `MERGE (a)-[r:TYPE {id: row.rid}]->(b) SET ...`.
- The link id is an idempotency key. One batch must not bind the same id to two different edges (`idempotency key conflict for relationship-import request`). Re-running the same id for the same edge is a no-op plus `SET`, so upserts stay single-edge.
- `db.link_id(rel, source, target)` builds a deterministic id unique across the whole graph: `(source * 1e9 + target) * 4 + type_code`. Node ids must be below 1,000,000,000 (Baton uses teams 1..999, entities from 100,000, issues from 1,000,000, tests from 900,000,000). `db.write_links` also drops duplicate rows inside a batch.
- Any link written without going through `db.py` must follow the same id scheme, or MERGE will create a second edge.
- A single statement MERGE cannot be followed by `SET`. Use `MATCH ... SET` for single edits.
- Batched `UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n` works and removes the links too.

## Reading

- No unanchored `MATCH (n)`. A label anchor (`MATCH (n:Team)`) or an id anchor is fine.
- `count(*)` per label or per link type works. `db.counts()` uses it.
- `WHERE e.id = $a OR e.id = $b` works. `IN`, `CONTAINS`, `min`, `max`, `count(DISTINCT)` and arithmetic do not; do those in Python.
- `RETURN r.id` fails with `unbound variable r`, even next to other `r.` columns. Link ids are write-only; recompute them with `db.link_id`.
- Rel property filters in patterns work: `-[r:ROUTES_TO {id: 7}]->`.

## algo.MSpaths

- Needs `sourceLabel`, `sourceProperty`, `targetLabel`, `targetProperty`. Value lists must be inlined string literals (list parameters are rejected), so `db.cypher_strings` escapes backslashes first, then single quotes.
- Use `relDirection: 'outgoing'` and `pairwise: false` (every source to every target).
- `maxLen` counts edges. Paths are simple. Pairs with no path are absent from the result.
- Over Bolt `path` is a native `neo4j.graph.Path`. Path nodes expose properties but not `id`; the node id is `node.element_id` (as a string). `db.ms_paths` returns plain dicts: `{"nodes": [names], "ids": [ints], "rels": [types], "weight": float}`. Issue nodes show as `#<number>`.

### Weighted search works

Tiny graph: entity `e1` has `ROUTES_TO` cheap-team at cost 5 (short, 1 hop) and `SEEN_IN` issue (cost 1) then `OWNED_BY` cheap-team (cost 1) (long, 2 hops, total 2).

| Query | Rows for e1 to cheap-team | pathWeight |
|---|---|---|
| `weightProp: 'cost'`, `pathCount: 1` | SEEN_IN, OWNED_BY | 2 |
| no weightProp, `pathCount: 1` | ROUTES_TO | 1 (hop count) |
| `weightProp: 'cost'`, `pathCount: 3` | both 2-hop paths, then ROUTES_TO | 2, 2, 5 |
| `weightProp: 'cost'`, `pathCount: 0` | only the tied cheapest paths | 2, 2 |

So `weightProp` changes which path wins, `pathWeight` is the sum of `cost` along the path (hop count when unweighted), and `pathCount` is per source and target pair, cheapest first. No MATCH-based fallback scorer was needed. `tests/test_db.py::test_ms_paths_prefers_cheap_path_over_short_one` guards this.

## Latency

Debug build (`cargo run`, unoptimized), local storage, no indexer, MacBook. Graph: 30 teams, 1,000 entities, 300 issues, 3,000 ROUTES_TO, 900 SEEN_IN, 300 OWNED_BY.

| Operation | Time |
|---|---|
| `ms_paths`, 5 sources, 30 targets, maxLen 3, pathCount 3, weighted (30 runs) | median 18.1 ms, p95 20.3 ms, max 21.7 ms (about 18 rows) |
| same, unweighted | median 18.9 ms, p95 22.2 ms |
| `routes_from_entities` (5 entities) | 7 ms |
| `routes_to_team` (102 links) | 17 ms |
| `all_routes` (3,000 links) | 440 ms |
| write 1,000 entities | 0.06 s |
| write 300 issues with links | 0.42 s |
| write 3,000 ROUTES_TO | 0.92 s |
| delete 1,330 nodes | 1.45 s |

Routing one issue is well under the budget, so the indexer and MinIO are not needed at this size. `all_routes` is slow-ish; learning passes should prefer `routes_from_entities` or `routes_to_team`.

## Shared graph etiquette

- `db.reset()` wipes every Team, Entity and Issue node. Only the thread that owns the current wave's graph work may call it.
- Tests use ids from 900,000,000 and the `zz-test-` name prefix and delete them afterwards.
- Unlabeled nodes (like the smoke check's) are not removed by `reset()`; delete them by id.
