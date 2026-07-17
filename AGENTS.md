# AGENTS.md · Agent Runtime Protocol

This repository is the personal AI "home." Agents running here follow this protocol.

## On Startup

1. Read `USER.md`, `SOUL.md`
2. In main sessions, read `MEMORY.md`
3. For domain tasks, check `knowledge/` first

## Memory

- Important facts → `memory/YYYY-MM-DD.md` (daily) or `MEMORY.md` (long-term)
- Do not rely on chat context alone; **writing files = real memory**
- **Conversation learning**: user saves chats to `knowledge/conversations/`; use `@agent-memory` to distill into `MEMORY.md` (not model training)

## Task Routing

- User `@my-core-agent` → read core skill, route to chat / research / writing / coding / memory
- User `@agent-xxx` explicitly → run that skill directly

## Tools

- Prefer read/write inside the project
- Confirm before destructive operations
- Web search: research tasks OK; do not overuse when not asked

## Output

- Follow language and style in `USER.md` by default
- Long tasks: brief plan first, then execute
