# Juno · Personal AI Agent

> **Beta (v0.1.0)** — Early preview. APIs, prompts, and UI may change without notice.  
> Use at your own discretion; [report issues](https://github.com/lij88079-jpg/juno-agent/issues) on GitHub.

**Juno** is a **personal AI headquarters** — not just a chatbot. Identity, memory, rules, skills, knowledge, and a Cursor-style web UI live in **one folder** you own. Swap models (local Ollama or cloud API), keep your data on disk, and extend behavior without retraining model weights.

---

## What you get

| Layer | What it does |
|-------|----------------|
| **Web Chat** (`/chat`) | Cursor-like UI: history sidebar, drag-and-drop files, @mentions, integrated terminal, mode switcher |
| **Studio** (`/studio`) | Edit MEMORY / USER, view synced conversations, add style training examples |
| **Brain** (`juno_brain.py`) | System prompt, per-turn **intent understanding**, tone guard, session memory |
| **Orchestrator** (`juno_orchestrator.py`) | Intent routing, prefetch, tool policy (Cursor Auto–lite) |
| **Agent** (`juno_agent.py`) | Multi-step tool loop: read / grep / search / shell / write (sandboxed) |
| **Cursor skills** (`.cursor/skills/`) | `@my-core-agent`, `@agent-coding`, `@agent-research`, etc. |

### Chat modes (bottom bar in `/chat`)

| Mode | Icon | Can do |
|------|------|--------|
| **Chat** | ○ | Talk only — no file or shell access |
| **Agent** | ∞ | Read/write files, run whitelisted shell, MCP tools |
| **Plan** | ◈ | Plan steps only — no write / shell / git |
| **Ask** | 👁 | Read-only: search, read, grep, web |

### Intent understanding

Every user message goes through **`analyze_user_turn`**: literal text → turn type (new task / continuation / feedback / command / holistic design…) → user goal → how to respond. Short replies (e.g. “ok”, “continue”, skeptical one-liners) are treated as **reactions to the previous turn**, not brand-new small talk. See `knowledge/juno-workflow.md` and `scripts/juno_brain.py`.

---

## Install from GitHub

**Requirements:** Python 3.10+. Optional: [Ollama](https://ollama.com/download) for fully local mode.

```bash
git clone https://github.com/lij88079-jpg/juno-agent.git
cd juno-agent

# Cloud API — copy example and add your key
copy config\chat.local.json.example config\chat.local.json   # Windows
# cp config/chat.local.json.example config/chat.local.json  # macOS / Linux

python scripts/juno_training_server.py
```

Open in browser:

- **Chat:** http://127.0.0.1:8765/chat  
- **Studio:** http://127.0.0.1:8765/studio  

Windows shortcuts (same server):

| Script | Purpose |
|--------|---------|
| `scripts/启动训练台.bat` | Start server + open Studio |
| `scripts/打开Juno对话.bat` | Start server + open Chat |
| `scripts/启动Juno.bat` | Local Ollama setup + chat |
| `scripts/安装Juno环境.bat` | First-time dependency install |

> **Beta** — Back up `USER.md`, `MEMORY.md`, and `config/chat.local.json` before upgrading.  
> **Never commit** API keys or chat sessions — they are listed in `.gitignore`.

### API setup (`config/chat.local.json`)

| Field | Example | Notes |
|-------|---------|--------|
| `provider` | `openai_compatible` or `ollama` | Cloud vs local |
| `api_base` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `model` | `deepseek-chat` | Model ID for your provider |
| `api_key` | `sk-...` | Required for cloud; omit for Ollama |

On first run, use **Model settings** in `/chat`, or edit `chat.local.json` directly.

---

## Quick start (Cursor)

Best when you want Juno inside your IDE for coding tasks.

1. Open this repo in **Cursor** (`File → Open Folder → juno-agent`).
2. Edit **`USER.md`** — who you are, language preference, boundaries.  
   Edit **`SOUL.md`** — Juno’s name, tone, and how it should behave.
3. Start a **new chat**, type **`@my-core-agent`**, and describe what you need.  
   Juno routes to chat / research / writing / coding / memory skills as appropriate.
4. Drop reference material into **`knowledge/`** (PDFs, notes, exports). Mention or @ files in chat when relevant.

**Tip:** `@agent-coding` for code changes, `@agent-research` for lookup, `@agent-memory` to summarize chats into MEMORY.

---

## Standalone — no Cursor, no cloud API

Run entirely on your machine with **Ollama** as the LLM backend. No API key required.

1. Install [Ollama](https://ollama.com/download).
2. Double-click **`scripts/启动Juno.bat`** (or run it from a terminal).  
   It pulls the default model (`qwen2.5:7b`) if missing and opens the chat UI.
3. Read **`独立存在.txt`** (standalone setup guide, Chinese) for troubleshooting.

| Component | Role |
|-----------|------|
| **Ollama** | Local LLM runtime |
| **Juno server** | Injects SOUL, USER, MEMORY, workflow, and skills into each reply |
| **Chat UI** | Browser at `http://127.0.0.1:8765/chat` |

Your identity and memory live in this folder — copy the whole directory to another PC to migrate.

---

## Standalone chat window (cloud API optional)

Use the web UI with **DeepSeek**, **OpenAI-compatible**, or other cloud endpoints for stronger models.

1. Double-click **`scripts/打开Juno对话.bat`**, or run `python scripts/juno_training_server.py`.
2. Open **http://127.0.0.1:8765/chat**.
3. First time: open **Model settings**, pick a preset or paste your API key.  
   Keys are stored in `config/chat.local.json` (gitignored).
4. Juno reads **SOUL / USER / MEMORY / training examples** on every turn.  
   Replies follow your persona files, not a generic assistant script.
5. History is saved under **`memory/chat-sessions/`** (local only, not pushed to GitHub).

**Agent mode:** switch to **∞ Agent** at the bottom to let Juno read files, edit code in allowed roots, and run whitelisted shell commands in the built-in terminal (no extra CMD windows).

---

## Auto-sync Cursor chats + Studio

Stop copy-pasting logs. With Cursor hooks configured, each Agent session can sync into **`knowledge/conversations/auto/`**.

| Action | How |
|--------|-----|
| **Open Studio** | http://127.0.0.1:8765/studio or `scripts/启动训练台.bat` |
| **Open Chat** | http://127.0.0.1:8765/chat |
| **Sync now** | Studio → **Sync now**, or `python scripts/sync_cursor_chats.py` |
| **Full rescan** | `python scripts/sync_cursor_chats.py --force` |
| **Digest into MEMORY** | In Cursor: `@agent-memory summarize the latest files in conversations/auto` |

**What Studio is for**

- Browse synced Cursor and web conversations  
- Edit **`MEMORY.md`** and **`USER.md`** in the browser  
- Add **style examples** to `training/examples.jsonl` (question → ideal answer)  
- Trigger manual sync and view sync status  

After each web chat, **`juno_sync_pipeline.py`** runs in the background (archive + optional auto-learn). This is **memory-style learning** (RAG + MEMORY + examples), **not** fine-tuning model weights.

---

## Project layout

```
juno-agent/
├── USER.md                 # Your profile — edit first
├── SOUL.md                 # Juno persona and tone rules
├── MEMORY.md               # Long-term memory (curated)
├── AGENTS.md               # Agent runtime protocol
├── VERSION                 # 0.1.0-beta
├── config/
│   ├── chat.json           # Default chat config
│   ├── chat.local.json.example
│   ├── agent-profile.json  # Tool sandbox, read roots, max steps
│   └── mcp-inbound.json    # MCP server list
├── .cursor/
│   ├── rules/              # Rules when this repo is open in Cursor
│   └── skills/             # agent-chat, agent-coding, my-core-agent, …
├── knowledge/              # PDFs, notes, reference docs
│   ├── juno-workflow.md    # Injected thinking framework
│   ├── auto-orchestration.md
│   └── conversations/auto/ # Auto-synced chats (gitignored)
├── training/
│   ├── chat.html           # Web chat UI
│   ├── studio.html         # Studio dashboard
│   ├── examples.jsonl      # Style training samples
│   └── cursor-*.js         # Terminal, explorer, @mentions, drag-drop
├── scripts/
│   ├── juno_training_server.py  # HTTP server on :8765
│   ├── juno_brain.py       # Prompts, intent, streaming
│   ├── juno_orchestrator.py
│   ├── juno_agent.py       # Tool agent loop
│   └── juno_tools.py       # read / write / grep / shell / …
└── memory/
    ├── chat-sessions/      # Web chat history (gitignored)
    └── daily/              # Daily logs (gitignored)
```

---

## Use Juno from other projects

A global copy of the core skill may live at `~/.cursor/skills/my-core-agent/`. From any workspace you can **`@my-core-agent`**; point Juno at this repo’s `USER.md` / `MEMORY.md` or work inside the juno-agent folder for full context.

---

## Extend Juno

| Goal | How |
|------|-----|
| New specialty | Add `.cursor/skills/your-skill/SKILL.md` |
| New rule | Add `.cursor/rules/your-rule.mdc` |
| New knowledge | Drop files in `knowledge/` or attach in `/chat` |
| Change personality | Edit `SOUL.md` |
| Tool allowlist / read roots | Edit `config/agent-profile.json` |
| Workflow / orchestration text | Edit `knowledge/juno-workflow.md`, `knowledge/auto-orchestration.md` |

---

## First-time setup

1. Read **`BOOTSTRAP.md`** if present — one-time checklist.  
2. Fill in **`USER.md`**.  
3. Set an API key **or** install Ollama for local mode.  
4. Start the server → open `/chat` → say hello.  

You can delete `BOOTSTRAP.md` after setup.

---

## Status

**Beta** — personal project; APIs and UX may change.  
Feedback: https://github.com/lij88079-jpg/juno-agent/issues
