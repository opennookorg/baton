# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

baton is in its initial stage. Update this file as the stack, commands, and layout take shape.

## Code style

- Never write code comments. Code should be self-explanatory through naming.
- Docstrings: one line, concise. No multi-line docstrings unless asked.
- Use top-level imports. Import inside functions only to break a circular import or for an optional or heavy dependency.
- Never use em-dashes in code or prose. Use a comma, colon, parentheses, or period instead.

## Skills

- Project skills live in `.agents/skills/` (symlinked into `.claude/skills/` for Claude Code) and are pinned in `skills-lock.json`.
- Add a skill: `npx skills add <owner/repo> --skill <name> -y`
- Restore skills from the lockfile: `npx skills install`
- Update skills: `npx skills update -p -y`
- Use the `find-skills` skill to discover skills on https://skills.sh/

## Git

- Branch off `main` for changes. Keep commits small and focused.
- Do not push or open PRs unless asked.
