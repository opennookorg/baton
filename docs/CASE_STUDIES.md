# Case studies

Baton is not a Kubernetes script. It routes any GitHub repo whose closed issues say who owned them. This page runs the same code, with no per-repo tuning, on Kubernetes and five other repos, and on one repo it refuses.

Every repo went through one command:

```bash
uv run python -m eval.onboard onboard <owner/name>
```

That runs the doctor, fetches owned closed issues, builds the name table, learns a graph in the repo's own HydraDB database and scores every line on the repo's held-out test set. Nothing was picked by looking at test scores. The doctor's pick was taken as is on every repo.

## Results

Each cell is top-1 / top-3 accuracy on the repo's test set (the newest 15% of its owned issues). `frozen` learns from the first part of the stream and stops. `count_only` keeps adding issues with no reweighting or passes. `baton` is the full learner. `lookup`, `naive_bayes` and `always_biggest` are the no-graph baselines from `eval/no_graph.py`.

| repo | signal | learn / test | frozen | count_only | baton | lookup | naive_bayes | always_biggest | misroutes avoided per 1,000 |
|---|---|---|---|---|---|---|---|---|---|
| kubernetes/kubernetes | label `sig/` | 1700 / 300 | 0.54 / 0.74 | 0.59 / 0.78 | 0.70 / 0.86 | 0.60 / 0.83 | 0.70 / 0.87 | 0.38 / 0.62 | 107 |
| rust-lang/rust | label `T-` | 1700 / 300 | 0.66 / 0.81 | 0.72 / 0.92 | 0.77 / 0.94 | 0.69 / 0.93 | 0.72 / 0.89 | 0.65 / 0.88 | 50 |
| NousResearch/hermes-agent | label `comp/` | 1700 / 300 | 0.33 / 0.72 | 0.44 / 0.74 | 0.53 / 0.87 | 0.46 / 0.80 | 0.55 / 0.84 | 0.27 / 0.57 | 90 |
| react/react | label `Component: ` | 1700 / 300 | 0.14 / 0.45 | 0.42 / 0.47 | 0.47 / 0.48 | 0.47 / 0.48 | 0.46 / 0.47 | 0.43 / 0.44 | 43 |
| earendil-works/pi | assignee | 727 / 128 | 0.06 / 0.20 | 0.37 / 0.66 | 0.41 / 0.60 | 0.40 / 0.64 | 0.37 / 0.60 | 0.11 / 0.70 | 47 |
| openclaw/openclaw | fixer | 1700 / 300 | 0.07 / 0.29 | 0.21 / 0.50 | 0.37 / 0.60 | 0.12 / 0.49 | 0.20 / 0.44 | 0.02 / 0.17 | 167 |
| octocat/Hello-World | refused by the doctor | | | | | | | | |

"Misroutes avoided" is Baton's top-1 gain over `count_only`, per 1,000 test issues. Each repo's numbers are in `results/repos/<owner>__<name>/summary.json` (Kubernetes: `results/curve.json` and `results/no_graph.json`).

What the table says:

- **Learning beats counting on every repo.** Baton's top-1 is above `count_only` on all six routed repos, by 43 to 167 misroutes per 1,000. Same graph, same issues, the only difference is the reweighting and the passes in `baton/learn.py` and `baton/passes.py`. It is above `frozen` everywhere by a wide margin, so a graph that keeps learning is worth more than one built once.
- **Naive Bayes is a strong baseline, and Baton does not always beat it.** On Kubernetes they tie at top-1 (0.70 each). On hermes-agent naive Bayes is ahead at top-1 (0.55 against 0.53) and Baton is ahead at top-3 (0.87 against 0.84). Baton's edge over a bag-of-words classifier is that every answer carries the path that produced it, and it keeps learning from each outcome without a retrain. It is not a large accuracy edge.
- **The ceiling is set by the repo, not the method.** Rust's `T-compiler` takes 56% of issues, so always-biggest already gets 0.65 and every method lands between 0.66 and 0.77. React's test period is dominated by an owner the learning period barely saw (below), so no method passes 0.48 at top-3.
- **openclaw's lead has a simpler explanation.** On openclaw the person who filed the issue fixed it 53% of the time, and Baton learns reporters as entities, so it routes many issues back to their reporter. A rule that only says "the reporter fixes it" would score 0.53 top-1 there, above Baton's 0.37. On the other five repos the reporter is the owner on 0 to 2% of test issues, so their gains do not come from this.
- **Small repos give noisy numbers.** pi has 128 test issues. The 95% interval on a top-1 near 0.4 is about ±8.5 points, wider than the gap between Baton, `lookup` and `count_only`. On pi, read the table as "Baton works", not as a ranking.

## How the doctor decides

`uv run python -m eval.onboard doctor <owner/name>` samples the newest 1,000 closed issues and measures three kinds of owner signal:

- a label family: labels that share a prefix, such as `sig/`, `T-`, `comp/` or `Component: `, with at least two distinct labels in the family,
- `fixer`: the author of the merged pull request (or commit) that closed the issue, never a bot,
- `assignee`: whoever the issue was assigned to.

Label families that describe triage rather than ownership (`kind/`, `priority/`, `status/`, `impact:`, `bug`, `good first issue` and so on, listed in `TRIAGE_FAMILIES` in `baton/doctor.py`) are skipped.

For each signal it reports:

| Column | Meaning |
|---|---|
| coverage | share of sampled issues that have an owner under this signal |
| owners | owners with at least 3 sampled issues |
| eff | effective number of owners, 1 / sum of squared shares |
| largest | the biggest owner's share of owned issues |
| seen | share of the newest 15% of owned issues whose owners all appear in the older 85% |
| owned | coverage times the repo's closed issues: how many owned issues Baton could learn from |

The score is `coverage × (1 − largest) × seen`. It rewards a signal that owns most issues, spreads them over several owners, and whose owners recur, because Baton can only route to an owner it has learned. The doctor recommends the best scoring signal that passes three checks. The thresholds come from the data, not from test scores:

- **At least 2 owners, and no owner with 80% or more of issues.** At 80%, always naming the biggest owner is already right 80% of the time, so routing has almost nothing to add. Below that, Kubernetes' biggest SIG takes 28% and every repo here stays at or under 56%.
- **At least 300 owned closed issues.** The test set is 15% of the owned issues, so 300 gives 45 test issues. With 45 issues the 95% interval on a top-1 score near 0.6 is about ±14 points (1.96 × √(0.6 × 0.4 / 45)). That is wider than Baton's 11-point gain over `count_only` on Kubernetes, so a smaller repo cannot show whether learning helps.
- **At least one issue has an owner at all.** A repo with no labels, no linked pull requests and no assignees has nothing to learn from.

Each repo's report is saved as `data/repos/<owner>__<name>/doctor.json` (Kubernetes: `data/doctor.json`).

| repo | closed issues | recommended signal | coverage | owners | eff | largest | seen | owned | verdict |
|---|---|---|---|---|---|---|---|---|---|
| kubernetes/kubernetes | 48,106 | label `sig/` | 85% | 20 | 7.4 | 28% | 100% | 41,034 | ok |
| rust-lang/rust | 53,527 | label `T-` | 81% | 15 | 2.9 | 56% | 100% | 43,464 | ok |
| NousResearch/hermes-agent | 21,644 | label `comp/` | 92% | 12 | 6.6 | 28% | 100% | 19,999 | ok |
| openclaw/openclaw | 59,512 | fixer | 61% | 37 | 16.6 | 14% | 87% | 36,064 | ok |
| react/react | 13,976 | label `Component: ` | 14% | 4 | 2.2 | 54% | 100% | 2,027 | ok |
| earendil-works/pi | 7,701 | assignee | 14% | 5 | 4.0 | 38% | 96% | 1,109 | ok |
| octocat/Hello-World | 2,589 | none | | | | | | | no owner signal |

The owner counts here are from the 1,000-issue sample. The graphs learn from more issues and so hold more owners (pi 11, react 20, rust 21, Kubernetes 22).

## Sizes

Kubernetes keeps its exact sizes: 2,000 issues split 1,700 learning and 300 test, a 3,000-issue reserve, batches of 100, a frozen line that stops after 200, and routing snapshots at 0, 500, 1,000 and 1,700. Any repo with 2,000 or more owned issues gets the same sizes. A smaller repo keeps the 85/15 split and scales the batch, the frozen cut and the snapshots to its learning stream, with snapshots on batch boundaries (`Sizes.scaled` in `baton/repos.py`).

## Per repo

### kubernetes/kubernetes

The original case. The doctor picks `sig/` labels, the same signal Baton was built on, and the onboarding path reproduces the original sizes and scores exactly. The demo issue and its four slider answers are in [DEMO.md](DEMO.md).

### rust-lang/rust

Owner signal: the `T-` team labels (`T-compiler`, `T-libs`, `T-rustdoc` and so on). 5,263 owned issues were fetched, 5,000 kept: 2,000 for the run and a 3,000 reserve. The graph has 21 teams and 1,233 entities.

Recent closed issues, routed over MCP and the API after the run:

- #165959, an internal compiler error. Baton: `T-compiler` 0.591, path `ice -> T-compiler`. Correct.
- #165969, a `UdpSocket` docs report. Baton: `T-libs` 0.282, path `behavior -> T-libs`. Correct.
- #165988, "`String::retain` is slower". Baton: `T-compiler` 0.364, then `T-libs` 0.219, both through `rustc version verbose`. The owner is `T-libs`: wrong at top-1, right at top-3. The issue template asks everyone to paste `rustc --version --verbose`, so that phrase became a hub entity linked to every team. See the limits below.

### NousResearch/hermes-agent

Owner signal: the `comp/` labels (`comp/gateway`, `comp/cli`, `comp/tools`, `comp/agent` and so on), on 92% of closed issues. 6,602 owned issues fetched, 5,000 kept. 12 teams, 3,055 entities: the most entities per issue of any repo here, because issues paste long logs.

- #156062, a gateway test failure. Baton: `comp/gateway` 0.406, path `tests/gateway -> comp/gateway`. Correct.
- #156089. Baton: `comp/agent` 0.205, path `feature -> comp/agent`. Correct, but on a weak word.
- #156063, an atomic file write bug. Baton: `comp/cli` 0.682 via `atomic write`, then `comp/tools` 0.093 via `write file`. The owner is `comp/tools`: right at top-3 only.
- #156070, a dashboard issue. Baton: gateway, desktop, cli, at confidence 0.16. A miss, and the low confidence says so.

### react/react

Owner signal: the `Component: ` labels. Only 14% of React's closed issues carry one, so 2,270 owned issues exist in all: 2,000 for the run and a reserve of 270.

The scores are low for every method because the owners drifted. The learning issues run from May 2016 to March 2024 and the test issues from April 2024 on. In the test set `Component: React Compiler` owns 152 of 300 issues, and it appears once in learning. `Component: Developer Tools` owns another 129. A router can only name an owner it has learned, so about half the test set is out of reach for all six lines.

- #35889, `<link rel="preload">` duplicated in SSR. Baton: `Component: Server Rendering` 0.538, path `html -> Component: Server Rendering`. Correct.
- #35821, `useDeferredValue` stuck on a stale value. Baton: Concurrent Features, Developer Tools, Build Infrastructure, confidence 0.23. The owner is `Component: Suspense`: a miss.
- #35015, View Transitions stalling. Baton: Developer Tools 0.439. The owner is `Component: DOM`: a miss.

The repo moved from `facebook/react` to `react/react`. Baton uses the name GitHub reports now, and `facebook/react` gets the unknown-repo error with the list of routed repos.

### earendil-works/pi

No label family carries ownership, so the doctor picks assignees: 14% of closed issues have one. Only 855 owned issues exist, under the 2,000 that get the full sizes, so `Sizes.scaled` gives 727 learning, 128 test, batches of 43 and snapshots at 0, 215, 430 and 727. The owners are 11 people, not teams.

- #12148, an open issue at the time ("Mistral Large 4 hangs when trying to use tools"). Baton: `vegarsti` 0.297, path `tool -> vegarsti`, then `mitsuhiko` and `badlogic`. It had no assignee yet, so there is nothing to score it against. `team_profile` shows `vegarsti` owns the tool-calling entities (`tool_choice`, `stopreason length`), so the route reads as sensible.

Always-biggest has the best top-3 (0.70) because three maintainers own most assigned issues. Baton's top-1 (0.41) is the best of the six lines.

### openclaw/openclaw

No label family passed the doctor, so it picks `fixer`: the author of the merged pull request that closed the issue, on 61% of closed issues. 5,810 owned issues were fetched and 5,000 kept. The owners are people, and many of them: the graph holds 438 fixers, 2,455 entities and 2,551 issues. The 2,000 issues in the run span only six weeks (October 6 to November 15, 2026), because openclaw closes issues fast.

Fixers turn over quickly. The biggest learning-period fixer (449 of 1,700 issues) fixes almost nothing in the test period, so always-biggest scores 0.02. 260 of the 300 test issues have a fixer the learning stream saw.

- #199318, consolidating a benchmark build check. Baton: `vincentkoc` 0.759, path `vincentkoc -> vincentkoc`. Correct.
- #199194, scheduled automations losing their scratch space. Baton: `daniel-lxs` 0.415, path `daniel-lxs -> daniel-lxs`, then `steipete` via `latest`. Correct.
- #199472, a misleading "Context overflow" cron notice. Baton: `masatohoshino` 0.232, path `masatohoshino -> masatohoshino`. Correct.

All three paths start at the reporter: maintainers file an issue and then fix it. That is a real pattern in this repo, and the reading above explains why it flatters Baton here. `roboclaw-bot` is a user account rather than a GitHub App, so the bot filter (`__typename == "Bot"` or a `[bot]` suffix) keeps it as a fixer, and it owns 45 of the test issues.

### octocat/Hello-World

The refusal case. No label family, no linked pull requests, no assignees. The doctor says `no owner signal` and `onboard` stops before fetching. Asking the API or MCP to route for it returns the doctor's reason:

```json
{"error": "unknown_repo", "detail": "octocat/Hello-World cannot be routed: no owner signal: no label family, fixer or assignee covers any issue"}
```

### Transcripts

The API and MCP calls above were made against the local server (`uv run uvicorn app.server:app`) and the stdio MCP server (`uv run python -m agent.mcp_server`) after `uv run python -m eval.restore_graph --all`. The same calls against the Cloud Run deployment are in the pull request that added this page.

## What does not work yet

- **The doctor's seen share is measured inside its sample.** It splits the newest 1,000 closed issues 85/15, not the real learning and test streams. React scored 100% seen, yet its real test period is dominated by an owner the learning stream saw once. A better check would measure seen share on the actual split after fetching, and warn before scoring.
- **Template boilerplate becomes entities.** Phrases every issue template asks for (`rustc version verbose` on rust) link to every team and pull routes toward the biggest one. There is no per-repo filter for template text yet, and adding one by hand per repo would be tuning.
- **The dashboard shows Kubernetes only.** The web pages hard-code the Kubernetes snapshot stages, a curve axis ending at 1,700 and Kubernetes example issues. Every other repo is routed through the API (`"repo"` in the body) and MCP (the `repo` argument and `list_repos`), not the dashboard.
- **The error key for a refused repo is `unknown_repo`.** The detail carries the doctor's reason, but a client that switches on the key cannot tell a refused repo from a misspelled one.
- **Bot accounts that are plain users count as owners.** The fixer filter drops GitHub Apps and `[bot]` logins only. openclaw's `roboclaw-bot` is a user account and is learned as a fixer.
- **The no-graph baselines ignore the reporter.** On openclaw a reporter-is-owner rule beats every line in the table. It is not in `eval/no_graph.py` yet.
- **Owners are whatever the signal says.** `fixer` and `assignee` route to people, not teams, and people leave. Re-run `onboard` to pick up new owners. There is no automatic refresh.
- **One HydraDB node is the bottleneck.** Onboarding several repos at once shares one node, which ran at about 190% CPU. A repo onboards in tens of minutes alone and in hours when three run together.
- **Fetching needs a GitHub token** (`GITHUB_TOKEN` or `gh auth token`) and stays inside GitHub's search limits by walking back in date windows.
