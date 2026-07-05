# Juno · Personal AI Agent

> **Beta (v0.1.0)** — Early preview. APIs, prompts, and UI may change without notice.  
> Use at your own discretion; [report issues](https://github.com/lij88079-jpg/juno-agent/issues) on GitHub.

**Juno**（朱诺）is a **personal AI headquarters** — not just a chatbot. Identity, memory, rules, skills, knowledge, and a Cursor-style web UI live in **one folder** you own. Swap models (local Ollama or cloud API), keep your data on disk, and extend behavior without retraining model weights.

---

## What you get

| Layer | What it does |
|-------|----------------|
| **Web Chat** (`/chat`) | Cursor-like UI: history sidebar, drag-and-drop files, @mentions, integrated terminal, mode switcher |
| **Studio** (`/studio`) | Edit MEMORY / USER, view synced conversations, add style training examples |
| **Brain** (`juno_brain.py`) | System prompt, per-turn **intent understanding**, tone guard, session memory |
| **Orchestrator** (`juno_orchestrator.py`) | Intent routing, prefetch, tool policy (Auto-lite) |
| **Agent** (`juno_agent.py`) | Multi-step tool loop: read / grep / search / shell / write (sandboxed) |
| **Cursor skills** (`.cursor/skills/`) | `@my-core-agent`, `@agent-coding`, `@agent-research`, etc. |

### Chat modes (bottom bar in `/chat`)

| Mode | Icon | Can do |
|------|------|--------|
| **Chat** | ○ | Talk only — no file or shell access |
| **Agent** | ∞ | Read/write files, run whitelisted shell, MCP tools |
| **Plan** | ◈ | Plan steps only — no write/shell/git |
| **Ask** | 👁 | Read-only: search, read, grep, web |

### Intent understanding (Beta highlight)

Every user message goes through **`analyze_user_turn`**: literal text → turn type (new task / continuation / feedback / command / holistic design…) → goal → what to reply. Short replies like “呵呵” or “继续” are treated as **responses to the previous turn**, not fresh small talk. See `knowledge/juno-workflow.md` and `scripts/juno_brain.py`.

---

## Install from GitHub

**Requirements:** Python 3.10+, optional [Ollama](https://ollama.com/download) for fully local mode.

```bash
git clone https://github.com/lij88079-jpg/juno-agent.git
cd juno-agent

# API config (cloud mode) — copy example and add your key
copy config\chat.local.json.example config\chat.local.json   # Windows
# cp config/chat.local.json.example config/chat.local.json  # macOS/Linux

# Start server
python scripts/juno_training_server.py
```

Open in browser:

- **Chat:** http://127.0.0.1:8765/chat  
- **Studio:** http://127.0.0.1:8765/studio  

Or double-click `scripts\启动训练台.bat` (Windows).

> **Beta** — Back up `USER.md`, `MEMORY.md`, and `config/chat.local.json` before upgrading.  
> **Never commit** `chat.local.json` or chat sessions — they are in `.gitignore`.

### API setup (`config/chat.local.json`)

| Field | Example | Notes |
|-------|---------|--------|
| `provider` | `openai_compatible` or `ollama` | Cloud vs local |
| `api_base` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `model` | `deepseek-chat` | Model id for your provider |
| `api_key` | `sk-...` | Required for cloud; omit for Ollama |

First run: use **⚙ Model settings** in `/chat`, or edit `chat.local.json` directly.

---

## Three ways to use Juno

### 1. Cursor (best for coding)

1. Open this folder in **Cursor** (`File → Open Folder → juno-agent`)
2. Edit **`USER.md`** (who you are) and **`SOUL.md`** (AI persona)
3. New chat → type **`@my-core-agent`** and describe the task
4. Put reference docs in **`knowledge/`**; @ files in chat when needed

Cursor Agent sessions can auto-sync to `knowledge/conversations/auto/` via hooks (see Studio).

### 2. Web UI (best for daily chat + Agent on any machine)

1. Start server (see above)
2. **Ctrl+Shift+R** hard refresh after updates
3. Drag files/folders into the composer (path pills like Cursor)
4. Use **∞ Agent** when Juno should read code or run commands in the integrated terminal

Conversations persist under `memory/chat-sessions/` (local only, not in git).

### 3. Fully local — no cloud API (`独立存在`)

1. Install **Ollama**
2. Double-click **`scripts\启动Juno.bat`** — pulls default model (`qwen2.5:7b`) and opens chat
3. Details: **`独立存在.txt`**

| Component | Role |
|-----------|------|
| **Ollama** | Local LLM |
| **Juno server** | Loads SOUL / USER / MEMORY / workflow injects |
| **Chat UI** | Browser at `:8765/chat` |

Copy the whole folder to another PC — identity and memory travel with it.

---

## Studio & memory (not model fine-tuning)

Juno learns via **files**, not weight training:

| Mechanism | Location | Purpose |
|-----------|----------|---------|
| Long-term memory | `MEMORY.md` | Facts, preferences, project notes |
| Daily log | `memory/daily/` | Raw session notes |
| Style examples | `training/examples.jsonl` | “Question → ideal answer” pairs |
| Auto-sync chats | `knowledge/conversations/auto/` | Cursor / web chat archive |
| Code index | `config/index/` (local) | Semantic search for Agent |

**Studio actions**

| Action | How |
|--------|-----|
| Open Studio | http://127.0.0.1:8765/studio or `scripts\启动训练台.bat` |
| Sync Cursor chats | Studio → **Sync now**, or `python scripts/sync_cursor_chats.py` |
| Full rescan | `python scripts/sync_cursor_chats.py --force` |
| Summarize into MEMORY | In Cursor: `@agent-memory summarize latest in conversations/auto` |

Pipeline after each chat: `juno_sync_pipeline.py` (background sync + optional auto-learn).

---

## Project layout

```
juno-agent/
├── USER.md                 # Your profile — edit first
├── SOUL.md                 # Juno persona & tone rules
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
│   ├── juno_training_server.py  # HTTP server :8765
│   ├── juno_brain.py       # Prompts, intent, streaming
│   ├── juno_orchestrator.py
│   ├── juno_agent.py       # Tool agent loop
│   └── juno_tools.py       # read / write / grep / shell / …
└── memory/
    ├── chat-sessions/      # Web chat history (gitignored)
    └── daily/              # Daily logs (gitignored)
```

---

## Extend Juno

| Goal | How |
|------|-----|
| New specialty | Add `.cursor/skills/your-skill/SKILL.md` |
| New rule | Add `.cursor/rules/your-rule.mdc` |
| New knowledge | Drop files in `knowledge/` or attach in `/chat` |
| Change personality | Edit `SOUL.md` |
| Change tool allowlist | Edit `config/agent-profile.json` |
| Workflow / orchestration copy | Edit `knowledge/juno-workflow.md`, `knowledge/auto-orchestration.md` |

Global copy of core skill (optional): `~/.cursor/skills/my-core-agent/` — use `@my-core-agent` from other repos.

---

## First-time setup

1. Read **`BOOTSTRAP.md`** if present — one-time initialization checklist  
2. Fill in **`USER.md`**  
3. Set API key or install Ollama  
4. Start server → open `/chat` → say hello  

Delete `BOOTSTRAP.md` after setup if you like.

---

## License & status

**Beta** — personal project, API surface unstable.  
Issues and ideas: https://github.com/lij88079-jpg/juno-agent/issues
