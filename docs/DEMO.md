# Baton demo shot list

For the 3-minute video and the 60-second backup. The words to say are in [PITCH.md](PITCH.md). Every result below was checked through `baton/service.py` against the baton graph at 1,700 issues.

## Before recording

```sh
scripts/start_hydradb.sh --background
uv run python -m eval.restore_graph
uv run uvicorn app.server:app --port 8000
```

- `restore_graph` puts the graph back in the baton end state, so the counters and the live route match the numbers below. It prints the counts: 22 teams, 1,225 entities, 2,286 issues.
- Open <http://localhost:8000> in a clean browser window at 1440 wide. The counters strip should read Issues learned 1,700, Links reweighted 13,621, Names merged 0, Shortcuts created 2,260, Misroutes avoided 90 (per 1,000 issues vs count-only).
- Have `docs/assets/curve.png` and `docs/assets/recovery.png` open in tabs as fallbacks.
- Set the dashboard theme to light or dark and keep it for the whole take.

## Shots

| Time | Shot | Action |
|---|---|---|
| 0:00 | Title card or the README top | Read the pitch line. |
| 0:20 | Dashboard, "Try an issue" | Paste the demo title (below). Leave the body empty. |
| 0:30 | Slider at **0** | Route. No teams: the graph is empty. |
| 0:40 | Slider at **500** | Route. Top team **sig/node** (wrong), path `event -> sig/node`. |
| 0:55 | Slider at **1,700** | Route. Top team **sig/scheduling**, confidence 0.468, path `scheduler -> sig/scheduling`. Hold on the path. |
| 1:10 | Curve card | Point at frozen (flat 0.543), count_only (0.593), baton (0.700), and the dotted naive Bayes line (0.703, no graph). |
| 1:50 | Curve card | Top-3 0.860. Mention sig labels hidden and tuning on the learning stream only. |
| 2:00 | Graph card | Type `scheduler`, press Show. |
| 2:15 | Terminal or `results/loadtest.json` | 453 requests, 0 failures, 1.7 s median, about 7 routes/s while learning. |
| 2:30 | Counters strip | 107 misroutes avoided per 1,000. Optional: `docs/assets/recovery.png`. |
| 2:50 | README | GPL-3.0 and `uv run python -m eval.run_curve`. |

### The demo issue

Paste this title at all three slider positions, body empty:

```
kube-scheduler: (Composite)PodGroup update event handlers don't distinguish a real update from a coalesced delete+create
```

It is test-set issue #142930, labelled `sig/scheduling`, and the graph never learned from it. What the service returns:

| Slider | Top team | Confidence | Path |
|---|---|---|---|
| 0 | none (7 entities found, 4 unknown, no links yet) | | |
| 500 | sig/node | 0.168 | `event -> sig/node` |
| 1,000 | sig/scheduling | 0.175 | `scheduler -> sig/scheduling` |
| 1,700 | sig/scheduling | 0.468 | `scheduler -> sig/scheduling` |

The live graph (no slider) gives the same answer as 1,700. Top 3 at 1,700: sig/scheduling, sig/node, sig/apps.

### The graph entity

Show `scheduler`: 36 nodes, 64 links, 10 teams, small enough to read on screen. The dashboard opens on `kubelet` (43 nodes, 17 teams), which is busier, so switch before the shot.

## The agent demo

Run this as its own clip, or in place of the graph shot if there is time.

```sh
claude --append-system-prompt "$(cat agent/TRIAGE.md)"
```

Check `claude mcp list` shows `baton` first. Then paste:

```
Route this GitHub issue to the team that owns it.

Title: kubectl config set panics on users.<name>.exec and users.<name>.auth-provider
```

It is test-set issue #142818, labelled `sig/cli`. What the tools return, so you know what to expect on screen:

- `route_issue` (title only): sig/node at confidence 0.139, then sig/cli, then sig/api-machinery. That is under 0.6, so the instructions make the agent check the other tools.
- `similar_past_issues`: 3 of the top 5 are sig/cli (#136533, #129299, #128808).
- `team_profile("sig/cli")`: pod, kubectl, port-forward and more at the top.
- The expected answer is **sig/cli**: route_issue's top team was wrong, and the extra lookups fix it. This is the point of the agent layer.

Do not let the agent call `record_outcome` in the recording. If anything was learned (through the agent, `/learn` or the load test), run `uv run python -m eval.restore_graph` before the next take.

## The 60-second backup

One take, no cuts:

1. README top, the pitch line (0:00 to 0:08).
2. Dashboard, the demo title at slider 0, 500, 1,700 (0:08 to 0:30).
3. Curve card, frozen 0.517, count_only 0.580, baton 0.670 (0:30 to 0:45).
4. `results/loadtest.json` or the counters strip (0:45 to 0:60).

## If something breaks

| Problem | Fix |
|---|---|
| HydraDB will not answer on 7687 | `scripts/start_hydradb.sh stop`, then start it again. Logs in `~/Projects/hydradb/.hydradb/node.log`. |
| Counters or routes differ from above | `uv run python -m eval.restore_graph` |
| A route is slow on camera | Route once before recording to warm the node, or cut to `docs/assets/curve.png`. |
| The dashboard is down | Show `docs/assets/dashboard.png` and the curve image. |
