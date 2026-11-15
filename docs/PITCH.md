# Baton pitch

Three minutes, in the order from `docs/SPEC.md`. Every number is from `results/` in this repo. The shot list for each part is in [DEMO.md](DEMO.md).

## The 3-minute talk

### 0:00 to 0:20: the problem

> Every big project has an ownership list: this component belongs to that team. It goes stale the day it is written. Teams split, people move, code changes hands, and new issues bounce between teams until someone who knows picks them up. Baton does not keep a list. It learns ownership from what actually gets fixed.

### 0:20 to 1:10: one real issue, at issue 0 and at issue 1,700

> This is a real Kubernetes issue from the test set, one Baton never learns from: "kube-scheduler: PodGroup update event handlers don't distinguish a real update from a coalesced delete+create". It was fixed by sig/scheduling.
>
> The slider routes it against the graph as it was at different points. At issue 0 the graph is empty: Baton knows the words but has seen no fixes, so it routes nothing. That is the honest starting point.
>
> At issue 500 it has a guess, sig/apps, through the word "delete". Wrong, and that is how count-based routing goes wrong: a generic word with lots of history wins.
>
> At issue 1,700 it says sig/scheduling, through "scheduler", with the path on screen. Nobody wrote "scheduler belongs to sig/scheduling" anywhere. Baton learned it from 1,700 fixed issues, and the path shows you why.

### 1:10 to 2:00: the curve

> Here is the whole test set: the newest 300 issues, scored after every batch of 100 learned. The labels in titles, like "[sig-node]", are hidden so nothing leaks.
>
> The grey line is a graph built once and never updated: 54 percent, flat forever. That is your ownership list. Orange adds every fixed issue to the same HydraDB graph but only counts: 59 percent. Blue is Baton. It rewards links that predicted the right team, penalises the ones that did not, adds direct shortcuts for strong patterns, and pulls in older issues where it knows too little. It ends at 70 percent top-1 and 86 percent top-3.
>
> Is the graph needed at all? We ran the best plain-store classifier we could write, naive Bayes on the same words, no graph. On this fixed test set it ties Baton: 70.3 against 70.0. But a router is used live, routing each issue before anyone knows the answer. On that stream of 1,700 issues Baton gets 70 percent and naive Bayes 64.5, and on the same issues the difference is far outside chance. And Baton shows the path for every route.
>
> Every learning value was tuned on the learning stream only. We built merging and splitting too, each has its own line, and we left them out of Baton because they did not help on the learning stream.

### 2:00 to 2:30: the graph and response time under load

> All of this lives in HydraDB. Here is the graph around "scheduler": the issues it appeared in, the teams that fixed them and the direct links Baton learned. Every route is one weighted `algo.MSpaths` query from the issue's entities to every team.
>
> Under load, 20 users for a minute, routing while it learns: 453 requests, zero failures, about 7 routes a second on one laptop, 1.7 seconds median. A single route alone takes about 180 milliseconds.

### 2:30 to 3:00: the business

> Learning on the graph beats count-only routing on the same graph by 11 points of top-1. That is 107 fewer misroutes for every 1,000 issues: issues that do not sit in the wrong queue, do not get bounced, and reach the people who can fix them first time. And when ownership changes, Baton follows. In a simulated reorg it was back above its old accuracy on the moved team within 500 issues, at 73 percent, while naive Bayes was still at 39. Nobody had to update a list. Baton is open source, GPL-3.0, and every number you saw reproduces with one command.

## The 60-second backup

> Ownership lists go stale the day they are written. Baton learns ownership from what actually gets fixed.
>
> It keeps a HydraDB graph of past issues, their components, words and paths, and the teams that fixed them. Every route is one weighted path query. Every fixed issue reweights the graph: right links get cheaper, wrong links get dearer.
>
> Take a real Kubernetes scheduler issue. On an empty graph Baton routes nothing. At 500 issues it guesses sig/node through the word "event", wrong. At 1,700 it says sig/scheduling, through "scheduler", and shows the path.
>
> On 300 newer issues it never learns from, a frozen graph gets 54 percent right. Counting on the same graph gets 59. Baton gets 70, with 86 percent in the top three: 107 fewer misroutes per 1,000 issues. A naive Bayes classifier with no graph ties it on that fixed set, but routing live, before the answer is known, Baton wins 70 to 64.5 and relearns a reorg twice as fast. Under load it served 453 requests with zero failures while it learned.
>
> No AI model in the router, tuned on the learning stream only, and one command reproduces the curve.

## Numbers used

| Claim | Value | Source |
|---|---|---|
| Frozen, count_only, baton test top-1 | 0.543, 0.593, 0.700 | `results/curve.json` |
| Baton test top-3 | 0.860 | `results/curve.json` |
| Misroutes avoided per 1,000, against count_only | 107 | `results/curve.json` `meta.summary` |
| Naive Bayes and lookup, no graph, test top-1 | 0.703, 0.603 | `results/no_graph.json` |
| Stream top-1, baton / naive Bayes / lookup | 0.700 / 0.645 / 0.617 | `results/tuning.json`, `results/no_graph.json` |
| Baton vs naive Bayes on the stream, paired | 175 vs 82 issues only one got right, McNemar z = 5.8 | `eval/no_graph.py` and the baton stream |
| Demo issue #142930 at 0 / 500 / 1,700 | none / sig/node / sig/scheduling (0.468) | `service.route_issue` with `as_of` |
| Load test | 453 requests, 0 failures, 1,700 ms median, about 7 routes/s | `results/loadtest.json` |
| Single route | 179 ms median, 549 ms p95 | live curve run, `results/curve.json` meta |
| Reorg recovery | moved-team top-1 0.647 before, 0.196 at the reorg, 0.726 at issue 1,400 (naive Bayes 0.392) | `results/recovery.json`, `results/no_graph.json` |
