# Juno · Personal AI Agent

> **Beta (v0.4)** — Early preview. Behaviour and APIs may change.  
> [Issues](https://github.com/lij88079-jpg/juno-agent/issues) · **Developer:** CIFS-EME Lee

**Juno** is a **personal AI headquarters**: identity, long-term memory, skills, knowledge, and a modern chat UI in one folder. Plug in a **local** or **cloud** model (any OpenAI-compatible endpoint). Juno learns from **files** — not by fine-tuning weights.

**Repo:** https://github.com/lij88079-jpg/juno-agent

---

## What you get

| Area | Description |
|------|-------------|
| **Identity** | `USER.md` + `SOUL.md` shape every reply |
| **Memory** | `MEMORY.md` + daily logs that survive restarts |
| **Chat UI** | Sessions, streaming, thinking/tool rails, terminal, drag-and-drop |
| **Modes** | Chat / Agent / Plan / Ask — same UI, different permissions |
| **Agent tools** | Read, search, edit, shell, web — multi-step loops |
| **Skills** | Extensible skill packs under `.cursor/skills/` (routing via core agent) |
| **Studio** | Edit memory, add examples, review archived chats |

---

## Quick start

```bash
git clone https://github.com/lij88079-jpg/juno-agent.git
cd juno-agent
```

**1. Local model (Ollama)** — install [Ollama](https://ollama.com), pull a chat model, keep defaults in `config/chat.json`.

**2. Cloud model** — copy and edit local config (gitignored):

```bash
# Windows
copy config\chat.local.json.example config\chat.local.json
# macOS / Linux
cp config/chat.local.json.example config/chat.local.json
```

```json
{
  "provider": "openai_compatible",
  "api_key": "sk-your-key-here",
  "model": "your-model-id",
  "api_base": "https://api.example.com"
}
```

**3. Paths** — put personal projects in `config/agent-profile.local.json` (see example). Do not commit that file.

**4. Run**

```bash
python scripts/juno_training_server.py
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8765/chat | Chat |
| http://127.0.0.1:8765/studio | Studio |

Windows helpers: `scripts/open-juno-chat.bat`, `scripts/restart-juno.py`.

---

## Architecture (high level)

```
Browser / IDE
      │
      ▼
Training server  (:8765)  — /chat  /studio  /api/*
      │
      ├── Chat  → conversation + memory
      └── Agent → tools + optional skill routing
      │
      ▼
Your configured LLM endpoint (local or cloud)
```

Internal module names and optional bridges may change between betas. Prefer configuring via `chat.local.json` / `agent-profile.local.json`.

---

## Modes

| Mode | Behaviour |
|------|-----------|
| **Chat** | Conversation; no file writes / shell by default |
| **Agent** | Can read/write, search, run allowed shell commands |
| **Plan** | Propose plans; avoid destructive actions |
| **Ask** | Read-only exploration |

---

## Memory & learning

- Long-term: `MEMORY.md`
- Daily: `memory/daily/`
- Examples: `training/examples.jsonl`
- Optional chat archive under `knowledge/conversations/` (local / gitignored paths)

Say「记住」in chat to curate lasting facts. Learning is **file-based**, not weight training.

---

## Security

- **Never commit** `*.local.json`, `.env`, API keys, or account pools
- Defaults ship without secrets; examples use placeholders
- Tighten `tools.writeRoots` / `shellAllowlist` for shared machines
- This is a personal HQ — treat the clone like a private notes vault if it holds real memory

---

## Project layout

```
USER.md / SOUL.md / MEMORY.md / AGENTS.md
config/          # public defaults + *.local.json (ignored)
knowledge/       # playbooks & docs
.cursor/skills/  # skill packs
scripts/         # server, brain, tools
training/        # chat UI + studio + examples
```

---

## Extending

Add a folder under `.cursor/skills/<name>/SKILL.md`, then route it from the core agent skill or call it with `@name`. Keep proprietary workflows and vendor mirrors **out of git** if you fork publicly.

---

## Troubleshooting

| Symptom | Try |
|---------|-----|
| Status not green | Check Ollama / API key / `api_base` |
| Agent cannot write | Expand `writeRoots` in local profile |
| Shell blocked | Adjust `shellAllowlist` |
| Huge prompts on small models | `"prompt_mode": "compact"` in local chat config |

---

## License / notice

Personal AI headquarters by **CIFS-EME Lee**. Beta software — use at your own discretion.
