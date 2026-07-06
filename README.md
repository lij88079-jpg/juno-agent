# Juno · Personal AI Agent

> **Beta (v0.1.0)** — Early preview. APIs, prompts, and UI may change without notice.  
> Use at your own discretion; [report issues](https://github.com/lij88079-jpg/juno-agent/issues) on GitHub.

**Juno** is a **personal AI headquarters** — not a disposable chat tab. One folder holds your AI’s identity, long-term memory, rules, skills, knowledge base, and a **Cursor-style web UI**. You choose the brain (local **Ollama** or any **OpenAI-compatible** cloud API). Juno learns through **files** (MEMORY, examples, synced chats), not model fine-tuning.

**Developer:** CIFS-EME Lee

**Repository:** https://github.com/lij88079-jpg/juno-agent

---

## Table of contents

1. [What Juno does](#what-juno-does)
2. [Architecture](#architecture)
3. [Requirements](#requirements)
4. [Install & first run](#install--first-run)
5. [Configuration reference](#configuration-reference)
6. [Quick start in Cursor](#quick-start-in-cursor)
7. [Web Chat UI (`/chat`)](#web-chat-ui-chat)
8. [Chat modes explained](#chat-modes-explained)
9. [Standalone local mode (Ollama)](#standalone-local-mode-ollama)
10. [Cloud API mode](#cloud-api-mode)
11. [Studio (`/studio`)](#studio-studio)
12. [Cursor chat auto-sync](#cursor-chat-auto-sync)
13. [Intent understanding](#intent-understanding)
14. [Agent tools reference](#agent-tools-reference)
15. [Memory & learning pipeline](#memory--learning-pipeline)
16. [Code index & search](#code-index--search)
17. [HTTP API overview](#http-api-overview)
18. [Security & privacy](#security--privacy)
19. [Troubleshooting](#troubleshooting)
20. [Project layout](#project-layout)
21. [Extending Juno](#extending-juno)
22. [First-time bootstrap](#first-time-bootstrap)

---

## What Juno does

| Capability | Description |
|------------|-------------|
| **Personal identity** | `USER.md` (you), `SOUL.md` (Juno), injected every turn — not a generic assistant |
| **Long-term memory** | `MEMORY.md` + daily logs; curated facts survive restarts |
| **Cursor-like Chat UI** | Sessions sidebar, streaming, thinking/tool rails, diff preview, integrated terminal |
| **Four modes** | Chat / Agent / Plan / Ask — same UI, different tool permissions |
| **Agent loop** | Multi-step read → grep → search → shell → edit, up to 24 steps (configurable) |
| **Intent layer** | Every message analyzed for turn type + goal before the model replies |
| **Drag & drop** | Drop files/folders into composer; path pills; ambiguous folder resolution |
| **Training Studio** | Edit memory, add Q→A style examples, browse synced Cursor chats |
| **Cursor skills** | `@my-core-agent`, `@agent-coding`, `@agent-research`, `@agent-writing`, `@agent-memory` |
| **MCP inbound** | Optional MCP servers via `config/mcp-inbound.json` |

---

## Architecture

```
User (browser / Cursor)
        │
        ▼
┌───────────────────────────────────────┐
│  juno_training_server.py  :8765       │
│  /chat  /studio  /api/*               │
└───────────────────────────────────────┘
        │
        ├── Chat mode ──► juno_brain.chat_stream()
        │
        └── Agent mode ► juno_agent.run_agent_stream_events()
                              │
                              ▼
                    ┌─────────────────┐
                    │ juno_orchestrator│  intent, prefetch, skills
                    └─────────────────┘
                              │
                    ┌─────────────────┐
                    │ juno_brain       │  prompts, analyze_user_turn,
                    │                  │  tone guard, temperature
                    └─────────────────┘
                              │
                    ┌─────────────────┐
                    │ juno_tools       │  read/write/grep/shell/…
                    │ juno_index         │  hybrid semantic search
                    └─────────────────┘
                              │
                              ▼
                    Ollama  or  OpenAI-compatible API
```

**Prompt stack (Agent, simplified):** UI mode → SOUL/USER/MEMORY → workflow inject → skill → orchestrator → scene + **【Understand user】** block → capabilities → context paths → conversation history → **tone guard** (last).

---

## Requirements

| Item | Notes |
|------|--------|
| **Python** | 3.10+ recommended |
| **OS** | Windows tested; macOS/Linux should work with path tweaks |
| **Browser** | Modern Chromium / Firefox / Edge for `/chat` |
| **Ollama** (optional) | Fully local LLM — https://ollama.com/download |
| **Cloud API** (optional) | DeepSeek, OpenAI, LM Studio, any OpenAI-compatible endpoint |
| **Cursor** (optional) | IDE integration + auto-sync hooks |

**Python deps:** mostly stdlib; server uses `urllib`. Index embedding may call Ollama `nomic-embed-text` if enabled in `agent-profile.json`.

---

## Install & first run

### 1. Clone

```bash
git clone https://github.com/lij88079-jpg/juno-agent.git
cd juno-agent
```

### 2. API config (cloud mode)

```bash
# Windows
copy config\chat.local.json.example config\chat.local.json

# macOS / Linux
cp config/chat.local.json.example config/chat.local.json
```

Edit `config/chat.local.json`:

```json
{
  "api_key": "sk-your-key-here",
  "model": "deepseek-chat",
  "api_base": "https://api.deepseek.com"
}
```

This file is **gitignored** — never commit it.

### 3. Customize paths (important)

Edit **`config/agent-profile.json`**:

- Replace `headquarters` with your clone path
- Set `tools.roots` and `tools.writeRoots` to folders Juno may read/write
- Set `index.roots` for code search scope

See [Configuration reference](#configuration-reference) below.

### 4. Start server

```bash
python scripts/juno_training_server.py
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8765/chat | Main chat UI |
| http://127.0.0.1:8765/studio | Memory & training dashboard |

**Windows shortcuts**

| File | Action |
|------|--------|
| `scripts/启动训练台.bat` | Start server + open Studio |
| `scripts/打开Juno对话.bat` | Start server + open Chat |
| `scripts/启动Juno.bat` | Install/pull Ollama model + open Chat |
| `scripts/安装Juno环境.bat` | First-time Python/env setup |

### 5. Verify

- Status dot in Chat header turns **green** when the model is reachable  
- `/api/chat/status` returns `configured: true`  
- Send “hello” in **Chat** mode first, then try **Agent** with a simple `@` file mention  

---

## Configuration reference

### `config/chat.json` — defaults & presets

Shared defaults. **`chat.local.json` overrides this.**

| Field | Meaning |
|-------|---------|
| `provider` | `ollama` or `openai_compatible` |
| `api_base` | Ollama URL or cloud endpoint |
| `model` | Model id string |
| `max_tokens` | Max completion tokens |
| `temperature` | Base sampling temperature |
| `presets` | Named presets shown in UI (Ollama, DeepSeek, LM Studio, …) |

Switch preset in Chat → **Model settings**, or POST `/api/chat/config`.

### `config/chat.local.json` — secrets (local only)

| Field | Meaning |
|-------|---------|
| `api_key` | Cloud provider key |
| `api_base` | Override endpoint |
| `model` | Override model |
| `prompt_mode` | `full` or `compact` (smaller prompts for 7B local models) |
| `env_file` | Optional: load `API_KEY` from a `.env` file path |

### `config/agent-profile.json` — agent sandbox

| Section | Purpose |
|---------|---------|
| `headquarters` | Juno home directory (absolute path) |
| `skills.*` | Skill id mapping for orchestrator |
| `index.*` | Semantic index: roots, chunk size, embed model, ignore rules |
| `tools.maxSteps` | Max agent tool iterations (default 24) |
| `tools.roots` | Directories Agent may read |
| `tools.writeRoots` | Directories Agent may write/edit |
| `tools.broadReadRoots` | Wider read for path attachment / drag-drop |
| `tools.shellAllowlist` | Prefix allowlist for `run_shell` (e.g. `git `, `pnpm `, `python `) |
| `tools.webSearch` | DuckDuckGo search toggle |

**Example:** to let Juno work on a second repo, add its path to `tools.roots`, `tools.writeRoots`, and `index.roots`.

### `USER.md` / `SOUL.md` / `MEMORY.md`

| File | Role |
|------|------|
| `USER.md` | Your name, language, use cases, red lines |
| `SOUL.md` | Juno name, tone, intro script, capability table |
| `MEMORY.md` | Curated long-term facts (projects, preferences, decisions) |

All three are loaded into the system prompt every session.

---

## Quick start in Cursor

Best for **coding** with full IDE context.

1. **Open folder:** `File → Open Folder → juno-agent` (or your clone path).
2. **Edit identity files:**
   - `USER.md` — who you are, what you use AI for, what to avoid
   - `SOUL.md` — how Juno should speak and behave
3. **New chat →** type **`@my-core-agent`** then your request.  
   Examples:
   - `@my-core-agent read USER.md and SOUL.md, introduce yourself in one sentence`
   - `@agent-coding fix the login bug in src/auth.ts`
   - `@agent-research summarize best practices for RAG chunking`
4. **Add knowledge:** put PDFs, notes, exports in `knowledge/`. Reference them with `@` or drag into web Chat.
5. **Optional:** install global skill at `~/.cursor/skills/my-core-agent/` to use `@my-core-agent` from **other** repos (point it at this HQ path in MEMORY).

---

## Web Chat UI (`/chat`)

| UI area | Function |
|---------|----------|
| **Left rail** | Home, explorer toggle, Studio link |
| **Session title** | Click to switch sessions; auto-named from first message |
| **History panel** | Past chats stored in `memory/chat-sessions/` |
| **Explorer** | File tree of configured roots; click to @ attach |
| **Composer** | Text input; **@** mentions; **/** slash commands; drag files/folders |
| **Path pills** | Attached paths shown inside composer (Cursor-style) |
| **Mode switcher** | Bottom bar: Chat / Agent / Plan / Ask |
| **Tool rail** | During Agent: plans, prefetch, tool calls, subagents, live output |
| **Terminal panel** | Streams stdout from background shell jobs (no extra CMD window) |
| **Model badge** | Current model; **Beta** label on header |
| **Settings menu** | Model presets, MCP, regenerate, delete session |

**Workflow tips**

- After code changes to `training/*.html` or `*.js`, **Ctrl+Shift+R** hard refresh.
- Use **Agent** when Juno must read repo files or run commands.
- Use **Ask** for read-only code review.
- Use **Plan** when you want a step list before any writes.

---

## Chat modes explained

| Mode | Tools | Typical use |
|------|-------|-------------|
| **Chat ○** | None | Q&A, brainstorming, writing drafts; uses MEMORY + uploads + index snippets only |
| **Agent ∞** | Full (within sandbox) | Implement features, run tests, edit files, terminal commands |
| **Plan ◈** | Read + search only | Architecture / migration plan; outputs steps, no `write_file` or `run_shell` |
| **Ask 👁** | Read-only | “Where is X defined?”, code exploration, no mutations |

The server injects an **authoritative mode block** each turn so Juno cannot claim the wrong mode from old chat history.

---

## Standalone local mode (Ollama)

No API key. Everything stays on your machine.

1. Install **Ollama** from https://ollama.com/download  
2. Run **`scripts/启动Juno.bat`** — pulls `qwen2.5:7b` if missing, starts server, opens browser  
3. In Model settings, confirm preset **Ollama 本地**  
4. See **`独立存在.txt`** for extended local setup (Chinese)

| Component | Role |
|-----------|------|
| Ollama | Serves LLM on `http://127.0.0.1:11434` |
| Juno server | Builds prompts from SOUL/USER/MEMORY/workflow |
| Browser UI | Chat at `:8765/chat` |

**Smaller models:** set `"prompt_mode": "compact"` in local config for shorter system prompts.

Copy the entire `juno-agent` folder to migrate identity + memory to another PC.

---

## Cloud API mode

Stronger models (DeepSeek, GPT, etc.) via OpenAI-compatible APIs.

1. Create `config/chat.local.json` with `api_key`, `api_base`, `model`  
2. Start server → open `/chat` → **Model settings** → pick **DeepSeek** or custom  
3. Juno uses **`prompt_mode: full`** for cloud models (full workflow + capabilities inject)

**Supported patterns**

| Provider | `api_base` example | `model` example |
|----------|-------------------|-----------------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| LM Studio | `http://127.0.0.1:1234/v1` | your loaded model name |

Conversations save to `memory/chat-sessions/` (local, gitignored).

---

## Studio (`/studio`)

Dashboard at **http://127.0.0.1:8765/studio**

| Tab | What you can do |
|-----|-----------------|
| **Dashboard** | Sync status, quick links to Chat, activity log |
| **How to chat** | Copy-paste prompts for Cursor |
| **Conversations** | Browse synced Cursor / web archives |
| **Memory** | Edit `MEMORY.md` in browser, save to disk |
| **User** | Edit `USER.md` |
| **Training** | Add rows to `training/examples.jsonl` (question + ideal answer + tags) |

**Style examples** teach tone (e.g. how to respond to pushback), not model weights. Tagged rows like `style`, `frustrated`, `holistic` guide the brain layer.

**Sync actions**

| Action | Command / UI |
|--------|----------------|
| Sync Cursor chats | Studio → **Sync now** |
| CLI sync | `python scripts/sync_cursor_chats.py` |
| Force full rescan | `python scripts/sync_cursor_chats.py --force` |
| Digest to MEMORY | In Cursor: `@agent-memory summarize latest in conversations/auto` |

---

## Cursor chat auto-sync

When Cursor hooks are configured, finished Agent sessions copy into **`knowledge/conversations/auto/`** as Markdown.

- No manual export/paste  
- Studio lists synced threads  
- `@agent-memory` can distill them into `MEMORY.md`  
- Auto-sync folder is **gitignored** (private chat content)

Post-chat pipeline: `juno_sync_pipeline.py` (background archive + optional auto-learn into `examples.jsonl`).

---

## Intent understanding

Juno’s **brain layer** runs **`analyze_user_turn()`** on every user message before generating a reply.

| Output | Meaning |
|--------|---------|
| **Turn type** | `new_task`, `continuation`, `feedback`, `command`, `question`, `design`, `holistic_scope`, `casual`, … |
| **User goal** | What they want achieved (result vs explanation vs behavior change) |
| **Linked prior** | Previous assistant line or session title this message responds to |
| **Response mode** | Act / explain / acknowledge / clarify / brief |

**Rules**

- Short replies (“ok”, “continue”, skeptical one-liners) → treated as **reactions to the last turn**, not new greetings  
- “This is just an example / I want the whole system” → **holistic_scope**, not a one-line patch  
- Injected as **【Understand user · required reading】** near the end of the system prompt  

Implementation: `scripts/juno_brain.py` (`analyze_user_turn`, `build_understanding_directive`, `tone_guard_directive`).  
Design doc: `knowledge/juno-workflow.md`, `knowledge/auto-orchestration.md`.

---

## Agent tools reference

Available in **Agent** mode (Plan/Ask restrict writes).

| Tool | Description |
|------|-------------|
| `read_file` | Read text file slice (`offset`, `limit`) |
| `list_dir` | List directory entries |
| `glob` | Find files by glob pattern |
| `grep` | Regex search under a path |
| `search_index` | Hybrid semantic + keyword search over indexed repos |
| `write_file` | Write/append within `writeRoots` |
| `str_replace` | Replace unique string in file |
| `apply_patch` | Apply unified patch |
| `delete_file` | Delete file (with confirm flag) |
| `run_shell` | Run allowlisted shell command; long jobs stream to UI terminal |
| `git` | status / diff / log / commit |
| `web_search` | DuckDuckGo search |
| `web_fetch` | Fetch URL as text |
| `read_lints` | Syntax/lint diagnostics for paths |
| `todo` | Agent task list (shown in UI) |
| `task` | Spawn subagent (`explore` / `shell`) |
| `mcp_call` | Call configured MCP server tool |

Tool schemas: `scripts/juno_tools.py` → `tool_schemas()`.

---

## Memory & learning pipeline

Juno does **not** fine-tune model weights. “Learning” means updating files:

| Layer | File / dir | Updated when |
|-------|------------|--------------|
| Long-term | `MEMORY.md` | You or `@agent-memory` after review |
| Daily | `memory/daily/` | Optional logging |
| Style | `training/examples.jsonl` | You in Studio; auto-learn (filtered) |
| Sessions | `memory/chat-sessions/` | Every web chat turn |
| Cursor archive | `knowledge/conversations/auto/` | Hook sync |

**Good example row** (`examples.jsonl`):

```json
{"question": "…", "answer": "…", "tags": ["style", "frustrated"], "created": "2026-07-05"}
```

Bad auto-learn rows (English boilerplate, snark) are filtered in `load_training_examples()`.

---

## Code index & search

Configured in `agent-profile.json` → `index`:

- **roots** — folders to index  
- **chunkChars** — chunk size (~900)  
- **hybridEmbed** — combine keyword + embedding scores  
- **embedModel** — default `nomic-embed-text:latest` via Ollama  
- **ignoreDirs / ignoreExtensions** — skip noise  

Rebuild: Studio or `POST /api/index/rebuild`.  
Agent calls `search_index` automatically; orchestrator may prefetch hits before the first tool step.

---

## HTTP API overview

Base: `http://127.0.0.1:8765`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/chat/status` | Model configured, provider, sync hint |
| GET | `/api/chat/sessions` | List sessions |
| POST | `/api/chat/new` | New session |
| POST | `/api/chat/send` | Send message (SSE stream if `stream: true`) |
| POST | `/api/chat/regenerate` | Regenerate last reply |
| POST | `/api/chat/attach-path` | Attach filesystem path |
| POST | `/api/chat/resolve-drop` | Resolve ambiguous dropped folder |
| GET | `/api/tools/tree` | Explorer file tree |
| GET | `/api/terminal/job` | Poll background shell output |
| GET/POST | `/api/memory`, `/api/user` | Read/write MEMORY / USER |
| POST | `/api/sync` | Trigger Cursor chat sync |

Full routes: `scripts/juno_training_server.py`.

---

## Security & privacy

| Do commit | Do **not** commit |
|-----------|-------------------|
| `chat.local.json.example` | `config/chat.local.json` (API keys) |
| `SOUL.md`, example MEMORY | Private `memory/chat-sessions/` |
| Code, skills, workflow docs | `knowledge/conversations/auto/` (personal chats) |

- **Shell allowlist** — Agent cannot run arbitrary commands  
- **Write roots** — edits confined to configured directories  
- **Beta** — review Agent diffs before keeping; use session revert in UI when available  

Before `git push`, run `git status` and confirm no `.local.json` or session files are staged.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Failed to fetch` in Chat | Restart `python scripts/juno_training_server.py`; check port 8765 free |
| Model not configured | Add `chat.local.json` or start Ollama |
| Agent “command not allowlisted” | Add prefix to `shellAllowlist` in `agent-profile.json` |
| Drag folder → “no readable text” | Use Agent mode; path must be under `broadReadRoots` |
| Stale UI after update | Ctrl+Shift+R on `/chat` |
| `gh` / GitHub timeout | Set `HTTPS_PROXY=http://127.0.0.1:7890` (or your proxy port) |
| Juno replies off-topic | Check mode (Chat vs Agent); add examples in `examples.jsonl` |
| Index empty | Run index rebuild; ensure Ollama embed model pulled |

---

## Project layout

```
juno-agent/
├── USER.md, SOUL.md, MEMORY.md, AGENTS.md
├── VERSION                          # 0.1.0-beta
├── config/
│   ├── chat.json                    # Defaults + UI presets
│   ├── chat.local.json.example
│   ├── agent-profile.json           # Sandbox, index, allowlist
│   └── mcp-inbound.json
├── .cursor/rules/                   # Cursor rules in this repo
├── .cursor/skills/                  # agent-chat, agent-coding, …
├── knowledge/
│   ├── juno-workflow.md             # Injected thinking framework
│   ├── auto-orchestration.md
│   ├── juno-capabilities.md
│   └── conversations/auto/          # Synced chats (gitignored)
├── training/
│   ├── chat.html, studio.html
│   ├── examples.jsonl
│   └── cursor-*.js                  # Terminal, explorer, mentions, DnD
├── scripts/
│   ├── juno_training_server.py
│   ├── juno_brain.py, juno_orchestrator.py, juno_agent.py
│   ├── juno_tools.py, juno_index.py
│   └── sync_cursor_chats.py, juno_sync_pipeline.py
└── memory/
    ├── chat-sessions/               # Web history (gitignored)
    └── daily/
```

---

## Extending Juno

| Goal | Action |
|------|--------|
| New skill | `.cursor/skills/your-skill/SKILL.md` + register in orchestrator if needed |
| New Cursor rule | `.cursor/rules/your-rule.mdc` |
| Change tone / intro | Edit `SOUL.md` |
| Change tool policy | Edit `config/agent-profile.json` |
| Change workflow text | Edit `knowledge/juno-workflow.md` (INJECT blocks) |
| Change orchestration | Edit `knowledge/auto-orchestration.md` |
| Add MCP server | `config/mcp-inbound.json` + restart server |

---

## First-time bootstrap

1. Read **`BOOTSTRAP.md`** — 5-step checklist (name, USER, test message, knowledge, MEMORY).  
2. Fill **`USER.md`** and **`SOUL.md`**.  
3. Set API key **or** install Ollama.  
4. Update **`agent-profile.json`** paths to your machine.  
5. `python scripts/juno_training_server.py` → open `/chat`.  
6. Delete `BOOTSTRAP.md` when done (optional).

**Test prompt (Cursor):**

```
@my-core-agent

Read USER.md and SOUL.md, introduce yourself in one sentence, and ask what I want to configure next.
```

---

## Status & feedback

**Beta (v0.1.0)** — personal project; behavior and APIs may change.  
Issues: https://github.com/lij88079-jpg/juno-agent/issues  

Back up `USER.md`, `MEMORY.md`, and `config/chat.local.json` before pulling updates.
