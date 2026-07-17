---
name: agent-memory
description: Learn from saved conversation logs and update Juno long-term memory. Use when user asks to learn from chats, summarize conversation logs, update memory, remember from chats, or @agent-memory after adding files to knowledge/conversations/.
user-invocable: true
allowed-tools: Read, Write, Edit, Grep, Glob
---

# Agent Memory · Learning from Conversations

You help **Juno** learn from **saved conversation logs** (not live training). Headquarters: Juno repo root (`./`)

## Input Sources

1. `knowledge/conversations/` — pasted or exported chats (`.md`, `.txt`)
2. `memory/daily/` — daily logs
3. User-pasted conversation in the current message

Read `USER.md`, `MEMORY.md`, `SOUL.md` first.

## Workflow

### Step 1 · Read

- Glob `knowledge/conversations/**/*.{md,txt}`
- If user specifies a file, read that only
- Sort by date (filename or mtime); prioritize recent unless user says "all"

### Step 2 · Extract (Do NOT Copy Raw Chat into MEMORY)

Extract only **durable** facts:

| Category | Examples |
|----------|----------|
| Identity/preferences | Language, style, how to address user |
| Long-term goals | Active projects, agent roadmap |
| Decisions | Naming Juno, tech choices |
| Red lines | Things not to do |
| Project context | Paths, repo names, roles |

**Skip**: one-off trivia, secrets (keys/passwords), others' private data, stale temporary tasks.

### Step 3 · Propose

Present a **Memory Update Draft** in English:

```markdown
## Proposed MEMORY.md Updates

### Add
- ...

### Update (replace old entries)
- ...

### Do Not Write (reason)
- ...
```

Ask: **"Confirm before I write to MEMORY.md"** — unless user said "write directly / no confirmation".

### Step 4 · Write

On confirmation:

- Merge into `MEMORY.md` under appropriate sections
- Optionally append one-line summary to `memory/daily/YYYY-MM-DD.md`
- Never delete large blocks of MEMORY without user OK

## Rules

- **No fabrication**: only extract what conversations actually say
- **No secrets** in MEMORY: if chat contains keys, warn user to redact source file
- **Deduplicate**: merge with existing MEMORY, don't repeat
- **Contradictions**: ask user which version is correct

## Triggers

- `@agent-memory learn from recent chats`
- `@agent-memory summarize conversations folder`
- `remember this conversation` → extract from current thread + offer MEMORY update

## Not in Scope

- Fine-tuning ML models
- Automatic background ingestion (user must save chats to folder or paste)
- Reading IDE transcripts unless user copies them here
