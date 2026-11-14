# Baton build spec

14 Nov 2026 · Kartik Labhshetwar

## Summary

Baton is an issue router that learns which team owns what. It sends each new bug to the right team and gets more accurate with every bug it handles. It enters Track 1, the self-improving graph.

- Win condition: an accuracy line that rises on issues the graph has never seen, and ends above two baselines.
- Why it needs the graph: every answer is a weighted path (issue → entity → team) found by HydraDB's own path search. Learning changes the weights and the shape of the graph.
- Cost: nothing. Everything runs on one laptop with free software and free public data.
- Inspired by: Korca Triage Agent, 3rd place at Neo4j's Aura Agent Hackathon (June 2026). Korca counts past tickets and never changes. Baton adds the learning.

Pitch line: "Ownership lists go stale the day they are written. Baton learns ownership from what actually gets fixed."

## Requirements

R1 to R5 are the minimum to compete. The rest make it a winning entry.

| # | Requirement | Priority |
|---|---|---|
| R1 | HydraDB is the only graph store. All routing reads and learning writes go through it. | Must |
| R2 | Given an issue's title and body, return the top 3 teams with a score and the graph path behind each. | Must |
| R3 | After each answer, the graph updates link weights from the real outcome, with no human feedback. | Must |
| R4 | Accuracy is measured on a fixed test set the graph never learns from, after every 100 issues. | Must |
| R5 | A chart shows Baton's line against a frozen baseline and a count-only baseline. | Must |
| R6 | Name merging, shortcut links and gap filling, each switchable on and off. | Should |
| R7 | One line on the chart per technique, showing what each adds. | Should |
| R8 | A dashboard page: chart, graph view, and a "paste an issue" box. | Should |
| R9 | A load test: routing requests while learning writes run, with response times. | Should |
| R10 | A simulated reorganisation: accuracy dips, then recovers by itself. | Nice to have |
| R11 | Dependabot pull requests as a second kind of item to route. | Nice to have |

Out of scope: user accounts, a hosted deployment, any paid service, paid AI-model calls, and real integrations with GitHub or ticketing tools.

## Setup

| Part | Tool | Cost |
|---|---|---|
| Graph database | HydraDB, built from the open-source repo | Free |
| Language | Python 3.10+ with the neo4j driver | Free |
| API and dashboard | FastAPI, plus one HTML page using Chart.js and Cytoscape.js | Free |
| Data | Public GitHub issues through the GitHub API with a free personal token | Free |
| Load test | Locust | Free |

Machine: Linux or macOS. Needs Rust 1.91+, a C/C++ toolchain, libcypher-parser and GraphBLAS.

macOS deps: `brew install just cmake pkg-config llvm suite-sparse coreutils` and `brew install cleishm/neo4j/libcypher-parser`.

Start a local HydraDB node:

```bash
git clone https://github.com/hydra-db/hydradb.git && cd hydradb
mkdir -p .hydradb/store .hydradb/cache
printf '%s\n' 'local-development-token-32-bytes' > .hydradb/auth-token

export CLOUD_PROVIDER=local
export LOCAL_PATH="$PWD/.hydradb/store"
export GRAPH_NAMESPACE=default
export GRAPH_ID=default
export GRAPH_CELL_ID=cell-0
export GRAPH_CELLS=cell-0
export GRAPH_NODE_ID=node-0
export GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687
export GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687
export GRAPH_DATA_CACHE_DIR="$PWD/.hydradb/cache"
export GRAPH_AUTH_TOKEN_FILE="$PWD/.hydradb/auth-token"
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432

cargo run --locked --features server-runtime --bin graph-node
```

The node listens for Neo4j drivers on 127.0.0.1:7687 and HTTP on 127.0.0.1:8443. On macOS the README adds two more exports before `cargo run`.

Python check (setup is done when it prints 999998):

```python
from neo4j import GraphDatabase

TOKEN = "local-development-token-32-bytes"
driver = GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("neo4j", TOKEN))
with driver.session(database="default") as s:
    s.run("MERGE (a {id: 999999})-[:SMOKE]->(b {id: 999998})").consume()
    print(s.run("MATCH (a {id: 999999})-[:SMOKE]->(b) RETURN b.id AS id").single()["id"])
```

Known risks:

- First build is slow. Start it before anything else.
- Local storage may break writes once the indexer runs (reported by team hyrev, who said the separate graph-indexer makes traversal 8 to 15 times faster). Start without the indexer. If path queries are too slow, switch storage to MinIO and add the indexer.
- The commands are copied from the repo's README and were not run by the spec author.

## Data

Use 2,000 closed issues from kubernetes/kubernetes. Each carries one or more `sig/` labels naming the owning team.

Fetch:

- `GET /repos/kubernetes/kubernetes/issues?state=closed&per_page=100&page=N` with a GitHub token.
- Skip any item with a `pull_request` field.
- Keep only issues with at least one `sig/` label, until you have 2,000.
- Save each as one JSON line: number, title, body, created date, reporter, list of `sig/` labels.

Split by date, never at random:

| Set | Issues | Use |
|---|---|---|
| Learning stream | Oldest 1,700 | Fed to the graph in date order, 100 at a time |
| Test set | Newest 300 | Scored after every batch. The graph never learns from these. |

Reserve pool: 3,000 extra older issues (older than the 2,000), downloaded once and kept on disk for gap filling.

Entities, extracted with plain code (no AI model):

- Component names from a fixed list: kubelet, kube-proxy, etcd, scheduler, kubectl, apiserver, CNI, CSI and so on.
- File paths and Go package paths, by pattern (`pkg/kubelet/...`, `staging/src/...`).
- Words in the title, lowercased, common words removed.
- Error phrases: text inside backticks or after `error:`, cut to the first six words.
- The reporter's username.

Keep an entity only if it appears in at least 3 learning issues.

Do not use labels as entities in the main run. `area/` and `kind/` labels may be run as a separate, clearly marked experiment.

Correct answer: a prediction is right when the top team is one of the issue's `sig/` labels. Report top-1 and top-3.

## Graph model

All links point from entities towards teams so one outgoing path search finds every route.

| Node | Properties | ID range |
|---|---|---|
| Team | id, name | 1 to 999 |
| Entity | id, name, kind (component, path, word, error, reporter) | 100,000+ |
| Issue | id, number, title | 1,000,000 + issue number |

| Link | Properties | Meaning |
|---|---|---|
| Entity -ROUTES_TO-> Team | strength, cost, hits, misses | The learned link. Reweighting changes this. |
| Entity -SEEN_IN-> Issue | cost (fixed 1) | The entity appeared in this past issue. |
| Issue -OWNED_BY-> Team | cost (fixed 1) | The team that really fixed it. |
| Entity -SAME_AS-> Entity | cost (fixed 0.1) | Written both ways when two names are merged. |

`cost = 1 / strength`, because path search returns lowest total weight. Strong links are cheap.

HydraDB rules:

- Node IDs are integers you supply. Keep a name-to-ID table in Python and save it to disk.
- `CREATE` twice makes duplicate links. Use `MERGE`, or `UNWIND $rows`, for every write.
- No arithmetic in queries. Read, compute in Python, then `SET`.
- Link properties can be updated: `MATCH (e {id: $e})-[r:ROUTES_TO]->(t {id: $t}) SET r.strength = $s, r.cost = $c`.
- `MERGE` takes no `ON CREATE`. Follow it with a separate `MATCH ... SET`.
- Patterns must be directed with one link type. Only `algo.*` path procedures cross several link types.
- No `IN`, `CONTAINS`, `min`, `max` or `count(DISTINCT)`. Filter in Python.
- List parameters are rejected in path procedures. Build names into the query text and escape quotes by hand.
- No text or vector search. Entity extraction in Python replaces it.

Batch load example:

```cypher
UNWIND $rows AS row
  MATCH (e:Entity {id: row.e}), (t:Team {id: row.t})
  MERGE (e)-[r:ROUTES_TO {id: row.rid}]->(t)
  SET r.strength = row.s, r.cost = row.c
```

## Routing

1. Extract the issue's entities in Python and keep the ones that exist in the graph.
2. Run one `algo.MSpaths` call from those entities to all teams, using `cost` as the weight.
3. For each path returned, add `1 / pathWeight` to the score of the team it ends at.
4. Return the top 3 teams, each with its share of the total score and its cheapest path.
5. Confidence is the top team's share of the total score.

```cypher
CALL algo.MSpaths({
  sourceLabel: 'Entity', sourceProperty: 'name',
  sourceValues: ['kubelet', 'pkg/kubelet/cm', 'oom'],
  targetLabel: 'Team', targetProperty: 'name',
  targetValues: ['sig/node', 'sig/network', 'sig/storage'],
  relTypes: ['ROUTES_TO', 'SEEN_IN', 'OWNED_BY', 'SAME_AS'],
  relDirection: 'outgoing',
  maxLen: 3, pathCount: 3, pairwise: false,
  weightProp: 'cost', resultLimit: 500
})
YIELD path, pathWeight
RETURN path, pathWeight
```

| Route | Steps | Meaning |
|---|---|---|
| Learned | Entity → Team | A direct link the graph has built and weighted |
| History | Entity → Issue → Team | A past issue mentioned this and that team fixed it |
| Merged | Entity → Entity → Team | Reached through a merged name |

Check early: `weightProp` and `pathWeight` exist in the engine source but were not run by the spec author. If weighted search misbehaves, fetch links with plain `MATCH` and score in Python. Keep `algo.MSpaths` for the displayed path.

Response shape:

```json
{
  "teams": [{"team": "sig/node", "share": 0.62, "path": ["kubelet", "sig/node"]}],
  "confidence": 0.62,
  "entities_found": 3,
  "entities_unknown": 1
}
```

## Learning loop

For every issue in the learning stream, in date order:

1. Route it and record the predicted team.
2. Reveal the real team from its `sig/` labels.
3. Write the issue into the graph: an Issue node, a SEEN_IN link from each entity, an OWNED_BY link to the real team.
4. Apply reweighting.
5. After every 100 issues, run the shortcut, merge and split passes, then score the test set.

| Technique | Organisers' name | Rule | Starting values |
|---|---|---|---|
| Reweighting | Edge reweighting | Right: add to strength on each ROUTES_TO link on the winning path. Wrong: multiply strength on links to the wrong team by a penalty, add to links to the real team. Then `cost = 1 / strength`. | Add 0.5, penalty × 0.8, floor 0.05 |
| Shortcuts | Path compression | When an entity reaches the same team through 3+ history paths, write a direct ROUTES_TO link. Once a shortcut exists, history issues older than the last 500 can be deleted. | Strength = number of history paths |
| Merging | Entity merge | Two entities of the same kind whose strengths point at the same teams, each with 10+ hits, get SAME_AS links both ways. | Similarity above 0.9 |
| Splitting | Entity split | An entity with many misses and no dominant team is split by a co-occurring entity (`timeout` becomes `timeout + kubelet`). The pair gets its own node and links. | 10+ misses, top team under 50% |
| Gap filling | Gap-driven ingestion | When confidence < 0.4, or fewer than 2 entities are known, pull 20 more past issues mentioning the unknown entities from the reserve pool and ingest them. | Confidence under 0.4 |

All arithmetic happens in Python. Read strengths with one MATCH, compute, write back in one UNWIND batch per issue.

Tune starting values on the learning stream only. Never adjust them by looking at test-set scores.

## Evaluation

After every 100 learning issues, route all 300 test issues with learning off, record top-1 and top-3. 18 points per line (0, 100, ..., 1700). Save every point to `results/curve.json` as produced.

| Line | What it is | What it proves |
|---|---|---|
| Frozen | Graph built from the first 200 issues, never updated | A frozen system stays flat |
| Count-only | Ingests every issue as history, no reweighting, shortcuts, merging or gap filling (Korca-style) | How much comes from more data |
| Baton | Everything on | What learning adds |
| One per technique | Count-only plus one technique | Which technique matters |

The claim to defend is the gap between Baton and count-only. If small, improve entity extraction first, then reweighting values.

Other numbers: misroutes avoided per 1,000 issues (Baton vs count-only); graph size before and after shortcut pruning; response time under load (Locust, 20 users on `/route` while learning writes, median and p95); optional share of issues whose `sig/` label changed after filing.

Recovery demo (optional): at issue 900, relabel one team's incoming issues to another team. Baton's line should dip and recover. Say clearly it is simulated.

## Demo app

One FastAPI program serves the API and a dashboard page at http://localhost:8000.

| Endpoint | Does |
|---|---|
| POST /route | Title and body in, top 3 teams, confidence and paths out. Queries HydraDB live. |
| POST /learn | Issue and real team in, applies the learning step. |
| GET /curve | Saved accuracy points for every line. |
| GET /graph?entity= | Nodes and links around one entity, with strengths. |
| GET /stats | Node and link counts, issues learned, merges and shortcuts. |

Dashboard, one screen, four parts:

- Accuracy chart: Baton, count-only and frozen lines, with toggles for per-technique lines.
- Try an issue: text box, top 3 teams and path. A slider picks learning stage: issue 0, 500, 1,000 or 1,700.
- Graph view: links around the chosen entity, thicker as strength grows. Merged names and shortcut links coloured differently.
- Counters: issues learned, links reweighted, names merged, shortcuts created, misroutes avoided.

The slider needs snapshots: at issues 0, 500, 1,000 and 1,700, save every ROUTES_TO strength to a file. To answer "as of issue 500", score the paths in Python with that file's strengths.

## Agent layer

Claude Code or Codex acts as the triage agent through a small MCP server over Baton's graph tools.

| Korca's tool | Baton's MCP tool | Returns |
|---|---|---|
| Semantic Ticket Finder | `similar_past_issues(title, body)` | Past issues sharing the most entities, with the fixing team |
| Expert Resolver | `route_issue(title, body)` | Top 3 teams, confidence and path |
| Client History Lookup | `reporter_history(username)` | Teams that fixed this reporter's earlier issues |
| Skill Match | `team_profile(team)` | Entities most strongly linked to a team |
| None | `record_outcome(issue, team)` | Feeds the real result back so the graph learns |

1. `agent/mcp_server.py` with the Python MCP SDK. Each tool calls the same functions as the API.
2. Register it with Claude Code or Codex as a local MCP server.
3. An instruction file: call `route_issue` first, check other tools when confidence < 0.6, answer with one team and the reason.
4. Demo: paste a bug into the agent, show it calling tools and naming the team with the path.

The curve stays on the plain router (no AI model). Optionally score the agent on 50 test issues and report separately.

## Build plan

| # | Step | Done when |
|---|---|---|
| 1 | Build and start HydraDB. Run the Python check. | Prints 999998 |
| 2 | Fetch 2,000 issues plus the 3,000 reserve pool | Two data files on disk |
| 3 | Entity extraction and name-to-ID table | 3+ entities per issue on average |
| 4 | Ingest the first 200 issues as history. `db.py` with batch writes. | Node and link counts match the data |
| 5 | Router with `algo.MSpaths` and weights | One issue returns teams and a path |
| 6 | Evaluation script. Frozen and count-only lines. | Two lines in curve.json |
| 7 | Reweighting and shortcuts. Baton line. | Baton ends above count-only |
| 8 | Merging, splitting, gap filling, one line each | A line per technique |
| 9 | API and dashboard | All four parts work in the browser |
| 10 | Load test, optional recovery demo | Response times recorded |
| 11 | README, pitch, 3-minute video, backup recording | Submitted |

Rules: if HydraDB is not working in two hours, ask in the HydraDB Discord. Do not start step 8 until step 7 beats count-only. Commit after every step. Stop adding features at Sunday 16:30.

## Pitch and risks

Demo order: problem (0:00 to 0:20), one real issue at issue 0 vs 1,700 (0:20 to 1:10), the curve (1:10 to 2:00), the graph and response time under load (2:00 to 2:30), the business and misroutes avoided (2:30 to 3:00).

Submission checklist: public GitHub repo with an open-source licence; README with setup and one command reproducing the curve; demo video of 3 minutes or less; 60-second backup recording; HydraDB named as the graph store with the query shown in the README.

| Risk | Fallback |
|---|---|
| HydraDB will not build | Use the repo's Dockerfile, or ask organisers for a hosted instance |
| Weighted path search misbehaves | Fetch links with MATCH and score in Python. Keep path search for the displayed path. |
| Path queries are slow | graph-indexer with MinIO, `maxLen` 2, prune old history |
| Baton does not beat count-only | Improve entity extraction, then tune reweighting on the learning stream |
| Out of time | Ship steps 1 to 7 with a static chart image and a recorded terminal run |
