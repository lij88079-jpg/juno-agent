---
name: agent-memory
description: Learn from saved conversation logs and update Juno long-term memory. Use when user asks to 学习对话、总结聊天记录、更新记忆、remember from chats, or @agent-memory after adding files to knowledge/conversations/.
user-invocable: true
allowed-tools: Read, Write, Edit, Grep, Glob
---

# Agent Memory · 从对话中学习

You help **Juno** learn from **saved conversation logs** (not live training). Headquarters: `C:\Users\solut xc\Desktop\my-ai-agent`

## Input sources

1. `knowledge/conversations/` — pasted or exported chats (`.md`, `.txt`)
2. `memory/daily/` — daily logs
3. User-pasted conversation in the current message

Read `USER.md`, `MEMORY.md`, `SOUL.md` first.

## Workflow

### Step 1 · Read

- Glob `knowledge/conversations/**/*.{md,txt}`
- If user specifies a file, read that only
- Sort by date (filename or mtime); prioritize recent unless user says "all"

### Step 2 · Extract (do NOT copy raw chat into MEMORY)

Extract only **durable** facts:

| Category | Examples |
|----------|----------|
| 身份/偏好 | 语言、风格、称呼 |
| 长期目标 | 在做的项目、智能体规划 |
| 决定 | 定名 Juno、技术选型 |
| 红线 | 不要做什么 |
| 项目上下文 | 路径、仓库名、角色分工 |

**Skip**: one-off trivia, secrets (keys/passwords), other people's private data, stale temporary tasks.

### Step 3 · Propose

Present a **Memory Update Draft** in Chinese:

```markdown
## 建议写入 MEMORY.md

### 新增
- ...

### 更新（替换旧条目）
- ...

### 不建议写入（原因）
- ...
```

Ask: **「确认后我再写入 MEMORY.md」** — unless user said "直接写入/不用确认".

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

- `@agent-memory 学习最近对话`
- `@agent-memory 总结 conversations 文件夹`
- `记住这次对话` → extract from current thread + offer MEMORY update

## Not in scope

- Fine-tuning ML models
- Automatic background ingestion (user must save chats to folder or paste)
- Reading Cursor transcripts unless user copies them here
