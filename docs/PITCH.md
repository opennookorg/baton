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
> The grey line is a graph built once and never updated: 52 percent, flat forever. That is your ownership list. Orange adds every fixed issue but only counts: 58 percent. Blue is Baton. It rewards links that predicted the right team, penalises the ones that did not, adds direct shortcuts for strong patterns, and pulls in older issues where it knows too little. It ends at 67 percent top-1 and 82 percent top-3.
>
> Every learning value was tuned on the learning stream only. We built merging and splitting too, each has its own line, and we left them out of Baton because they did not help on the learning stream.

### 2:00 to 2:30: the graph and response time under load

> All of this lives in HydraDB. Here is the graph around "scheduler": the issues it appeared in, the teams that fixed them and the direct links Baton learned. Every route is one weighted `algo.MSpaths` query from the issue's entities to every team.
>
> Under load, 20 users for a minute, routing while it learns: 643 requests, zero failures, about 10 routes a second on one laptop, 1.2 seconds median. A single route alone takes about 220 milliseconds.

### 2:30 to 3:00: the business

> Baton beats count-only routing by 9 points of top-1. That is 90 fewer misroutes for every 1,000 issues: 90 issues that do not sit in the wrong queue, do not get bounced, and reach the people who can fix them first time. And when ownership changes, Baton follows. In a simulated reorg it relearned the moved team's work within 500 issues. Nobody had to update a list. Baton is open source, GPL-3.0, and every number you saw reproduces with one command.

## The 60-second backup

> Ownership lists go stale the day they are written. Baton learns ownership from what actually gets fixed.
>
> It keeps a HydraDB graph of past issues, their components, words and paths, and the teams that fixed them. Every route is one weighted path query. Every fixed issue reweights the graph: right links get cheaper, wrong links get dearer.
>
> Take a real Kubernetes scheduler issue. On an empty graph Baton routes nothing. At 500 issues it guesses sig/apps, wrong. At 1,700 it says sig/scheduling, through "scheduler", and shows the path.
>
> On 300 newer issues it never learns from, a frozen graph gets 52 percent right. Counting gets 58. Baton gets 67, with 82 percent in the top three. That is 90 fewer misroutes per 1,000 issues. Under load it served 643 requests with zero failures while it learned.
>
> No AI model in the router, tuned on the learning stream only, and one command reproduces the curve.

## Numbers used

| Claim | Value | Source |
|---|---|---|
| Frozen, count_only, baton test top-1 | 0.517, 0.580, 0.670 | `results/curve.json` |
| Baton test top-3 | 0.823 | `results/curve.json` |
| Misroutes avoided per 1,000 | 90 | `results/curve.json` `meta.summary` |
| Demo issue #142930 at 0 / 500 / 1,700 | none / sig/apps / sig/scheduling (0.261) | `service.route_issue` with `as_of` |
| Load test | 643 requests, 0 failures, 1,200 ms median, about 10 routes/s | `results/loadtest.json` |
| Single route | 220 ms median | route profile in `results/loadtest.json` |
| Reorg recovery | moved-team top-1 0.176 at the reorg, 0.804 at issue 1,400 | `results/recovery.json` |
