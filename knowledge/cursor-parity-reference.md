# IDE Agent → Juno Capability Parity Reference

> Maps deep IDE integration patterns (indexing, tool chains, orchestration) to Juno modules.
> Juno does not replicate closed-source products—only the **architecture pattern**.

---

## 1. Three-Layer Architecture

```
UI (Chat / Composer / @mention)
        ↓
Agent orchestration (plan → pick tool → observe → replan)
        ↓
Tools (read / write / grep / terminal / MCP / …)
        ↓
LLM API (cloud or local)
        ↓
Context (open files + repo index + rules + memory)
```

**Juno mapping:**

| Layer | Juno | Path |
|-------|------|------|
| UI | `training/chat.html` + Agent toggle | ✅ |
| Orchestration | `scripts/juno_agent.py` | ✅ v1 |
| Tools | `scripts/juno_tools.py` | ✅ read/search/grep/shell |
| Model | `scripts/juno_brain.py` + Ollama/API | ✅ |
| Context | SOUL/USER/MEMORY + `juno_index.py` | ✅ keyword index |

---

## 2. IDE Deep Integration

| IDE capability | Concept | Juno reference |
|----------------|---------|----------------|
| Current open files | Editor context injection | Phase 2: POST `/api/context/open-files` |
| @ file / @ folder | Exact path in prompt | Agent `read_file` + user path |
| @codebase | Full-repo semantic search | `juno_index.search()` → Phase 2 vector embed |
| Project rules | Always in system prompt | `.cursor/rules` + `SOUL.md` |
| Skills | Task routing | `.cursor/skills/my-core-agent` etc. |
| Terminal | run_command tool | `juno_tools.run_shell` (allowlist) |
| MCP | External tool protocol | Phase 3: `mcp/juno-server` |
| Hook sync | stop hook → script | `juno_hook_sync.py` ✅ |

**Core principles:**
- **Retrieve before generate**; never invent file contents
- **Tool results feed back** in multi-step loop—not one-shot answers
- **Sandbox**: tools touch allowed paths only

---

## 3. Indexing the Whole Repo (@codebase)

### Typical pattern
1. Chunk workspace files
2. Embed or hybrid retrieval
3. Question → top-K → inject context
4. Incremental re-index on change

### Juno Phase 1 (done)
- `config/agent-profile.json` → `index.roots`
- `scripts/juno_index.py` → TF-IDF chunks + search
- API: `GET /api/index/status`, `GET /api/index/search?q=`, `POST /api/index/rebuild`

### Juno Phase 2
- [ ] Ollama `nomic-embed-text` vector index
- [ ] File watcher / git hook incremental update
- [ ] Ignore rules (`.cursorignore`-style)
- [ ] Auto retrieval in Chat mode—not Agent only

---

## 4. Tool Chain (Agent Tools)

| Tool | Purpose | Juno |
|------|---------|------|
| Read | File slice | `read_file` ✅ |
| Write | Create/overwrite | Phase 2 |
| StrReplace / Edit | Precise replace | Phase 2 |
| Grep / SemanticSearch | Search | `grep` + `search_index` ✅ |
| Shell | Run commands | `run_shell` (allowlist) ✅ |
| Delete | Remove file | Phase 2 (confirm) |
| Task / sub-agent | Parallel explore | Phase 3 |
| MCP | Third-party | Phase 3 |

### Agent loop (ReAct pattern)
```
User message
  → index prefetch into context
  → LLM: tool call or final answer
  → if tool → execute → result as user message
  → repeat until answer or max_steps
```
Implementation: `scripts/juno_agent.py`

---

## 5. Recommended Split

| Scenario | Use |
|----------|-----|
| Large refactors, CI, big code changes | **IDE @my-core-agent** |
| Private chat, offline, MEMORY | **Juno window** |
| Read MEMORY / training / archive | **Juno training UI** |
| Shared | SOUL.md, USER.md, MEMORY.md, `knowledge/conversations/auto/` |

**Unified memory, dual entry** — no forced UI merge.

---

## 6. Phase 3: Juno MCP Server (IDE Calls Juno)

| MCP Tool | Purpose |
|----------|---------|
| `juno_search_memory` | Search MEMORY + conversations |
| `juno_search_index` | Search Juno index |
| `juno_append_memory` | Append to MEMORY |
| `juno_sync` | Trigger sync pipeline |

Register: IDE Settings → MCP → point to `my-ai-agent/mcp/`

---

## 7. Model Layer

| | IDE subscription | Juno standalone |
|--|------------------|-----------------|
| Default | Cloud LLM API | Ollama 7B |
| Upgrade | Included in subscription | Swap API or GPU 72B |
| Ceiling | Product-grade agent | Model + tool completeness |

**Takeaway:** Tooling and indexing can approach IDE agents; **reasoning ceiling** is the model, not the UI.

---

## 8. System Summary (Injectable)

```
Agent behavior reference:
1. For code/project: search_index or read_file before answering
2. Never invent paths, functions, or file contents
3. Multi-step tasks: split steps; max ~2 tools per step
4. On complaints: acknowledge the issue, not generic greetings
5. Refuse clearly what you cannot do (prod DB writes, force push)
```

---

## 9. Maintenance

- After large code changes: `python scripts/juno_index.py`
- New project root: `config/agent-profile.json` → `index.roots` + `tools.roots`
- Shell allowlist: same file `tools.shellAllowlist`
- Conversation archive: Hook → `juno_hook_sync.py`

---

*Last updated: 2026-07-05 · Juno v0.2.0 Agent phase*
