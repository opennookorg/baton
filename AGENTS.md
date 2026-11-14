# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

Baton is an issue router that learns which team owns what, built on a HydraDB graph. Read `docs/SPEC.md` before any work: it is the source of truth for the graph model, routing, learning rules, evaluation and demo.

## Layout and ownership

Work is split across parallel worktree threads. Each thread owns its files. Do not edit files another thread owns; if you need a change there, say so in your final report.

| Path | Owner | Contents |
|---|---|---|
| `scripts/start_hydradb.sh`, `baton/db.py`, `docs/HYDRADB_NOTES.md` | HydraDB thread | Starting the node, driver, batch writes, `algo.MSpaths` wrapper |
| `data/fetch_issues.py`, `data/*.jsonl`, `baton/entities.py`, `baton/ids.py` | Data thread | Fetching issues, entity extraction, name-to-ID table |
| `app/` | Dashboard thread | FastAPI server and `app/static/index.html` |
| `agent/`, `eval/loadtest.py` | Agent thread | MCP server, agent instructions, Locust load test |
| `baton/ingest.py`, `baton/router.py`, `baton/service.py`, `eval/run_curve.py` | Core thread (wave 2) | Ingest, routing, evaluation |
| `baton/learn.py`, `baton/passes.py` | Learning thread (wave 3) | Reweighting, shortcuts, merging, splitting, gap filling |
| `baton/config.py`, `baton/models.py`, `AGENTS.md`, `docs/SPEC.md`, `pyproject.toml` | Main thread | Shared contracts. Propose changes, do not make them. |

`baton/service.py` is the only interface the API and MCP server call. Code against its signatures. Until the core thread implements it, use a local fake in your own tests.

## Shared HydraDB

There is one HydraDB node on this machine (bolt `127.0.0.1:7687`, HTTP `127.0.0.1:8443`), cloned and built at `~/Projects/hydradb` (override with `BATON_HYDRADB_HOME`). Start it with `scripts/start_hydradb.sh`. The graph is shared state: only the thread that owns the current wave's graph work may write to it. Other threads read only, or mock it.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest`
- API and dashboard: `uv run uvicorn app.server:app --port 8000`
- Curve: `uv run python -m eval.run_curve`

## Code style

- Never write code comments. Code should be self-explanatory through naming.
- Docstrings: one line, concise. No multi-line docstrings unless asked.
- Use top-level imports. Import inside functions only to break a circular import or for an optional or heavy dependency.
- Never use em-dashes in code or prose. Use a comma, colon, parentheses, or period instead.
- No paid services or paid AI-model calls. Entity extraction and routing are plain code.
- Tune learning values on the learning stream only. Never look at test-set scores to pick them.

## Skills

- Project skills live in `.agents/skills/` (symlinked into `.claude/skills/` for Claude Code) and are pinned in `skills-lock.json`.
- Add a skill: `npx skills add <owner/repo> --skill <name> -y`
- Restore skills from the lockfile: `npx skills install`
- Use the `find-skills` skill to discover skills on https://skills.sh/

## Git workflow

- Each thread works in its own worktree on its own branch, started from `origin/main`.
- Commit after every working step, with small focused commits.
- To land: `git fetch origin && git rebase origin/main`, run `uv run pytest`, push the branch, open a PR with `gh pr create --base main`, then merge it with `gh pr merge --squash --delete-branch`.
- Never force-push `main`. Never commit secrets or tokens.
