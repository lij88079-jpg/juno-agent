# IDE Agent Open References → Juno Implementation Map

> Public open-source projects and cookbooks that inform Juno design. This is **not** a claim of reverse-engineering any proprietary IDE product.

## Official & Cookbook References

| Repository | Purpose | Juno implementation |
|------------|---------|---------------------|
| [cursor/agent-trace](https://github.com/cursor/agent-trace) | Line-level AI attribution, trace records | `scripts/juno_agent_trace.py` · `.agent-trace/traces.jsonl` · Review line diff |
| [cursor/cookbook/sdk/agent-kanban](https://github.com/cursor/cookbook) | Multi-agent kanban, cloud agent cards | `#agents-drawer` Agents panel · subagent tabs |
| [cursor/cookbook/sdk/dag-task-runner](https://github.com/cursor/cookbook) | Sub-task DAG orchestration | `scripts/juno_subagent.py` · `task` tool |
| [cursor/cookbook/sdk/coding-agent-cli](https://github.com/cursor/cookbook) | Shell output / CLI mode | `#terminal-panel` · terminal UI module |
| [cursor/mcp-servers](https://github.com/cursor/mcp-servers) | MCP examples | `config/mcp-inbound.json` · `#mcp-modal` · merge `~/.cursor/mcp.json` |
| [cursor/plugins](https://github.com/cursor/plugins) | Plugin templates | Reference for rules/skills injection |

## Community IDE / Agent UI References

| Project | Borrowed ideas | Juno |
|---------|----------------|------|
| [voideditor/void](https://github.com/voideditor/void) | VS Code fork, agent sidebar | Activity Bar + chat-panel layout |
| [njbinbin-piscis/AgentZ](https://github.com/njbinbin-piscis/AgentZ) | Cmd+K inline diff, assistant panel | inline-edit module · composer-v2 |
| [continue-dev/continue](https://github.com/continuedev/continue) | @context, index, slash commands | `@mention` tabs · `/` slash commands |
| [21st-dev/agent-elements](https://github.com/21st-dev/agent-elements) | EditTool diff + approval UI | Review bar · hunk Accept/Reject |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) | Thread + Composer components | composer-v2 · streaming rail |

## Capability Status (v17 injection)

| Capability | Juno | Status |
|------------|------|--------|
| Agent tool chain | `juno_agent.py` + tools | ✅ |
| Chat / Agent / Plan / Ask modes | `resolve_ui_mode()` | ✅ |
| Thinking / reasoning stream | `reasoning_delta` → Thought panel | ✅ |
| @file / @codebase | mention picker | ✅ |
| @Rules / @Docs / @Folder | `GET /api/mention/sources` | ✅ v17 |
| @Git / @Web | git status inject · web hint | ✅ v17 |
| `/` slash commands | slash-command module | ✅ v17 |
| File explorer | explorer module · `GET /api/tools/tree` | ✅ v17 |
| MCP management UI | mcp-modal module | ✅ v17 |
| Review + Monaco diff | diff-editor module | ✅ |
| Cmd+K inline edit | cmdk module | ✅ |
| Terminal output panel | terminal module | ✅ (read-only, not PTY) |
| Subagent / task | `juno_subagent.py` | ✅ |
| Rules / Skills inject | `juno_skills.py` | ✅ |
| IDE open-file context | `memory/ide-context.json` | ✅ |
| Full VS Code workbench | — | ❌ needs desktop IDE |
| Proprietary shadow workspace index | — | ❌ not available |
| Interactive PTY terminal | — | ⏳ xterm.js planned |

## APIs (v17)

- `GET /api/tools/tree?path=&depth=2` — file tree (Explorer)
- `GET /api/mention/sources?kind=rules|docs|folder|git|web|files&q=` — extended @mention
- `GET /api/mcp/servers` — MCP list (UI modal)

## Frontend Modules (`training/`)

| File | Role |
|------|------|
| `cursor-ui.js` | Review · Agents · @mention tabs |
| `cursor-explorer.js` | Left file explorer |
| `cursor-slash.js` | `/new` `/mode` `/reindex` etc. |
| `cursor-mcp-modal.js` | MCP servers modal |
| `cursor-diff-editor.js` | Monaco side-by-side diff |
| `cursor-terminal.js` | Shell output panel |
| `cursor-cmdk.js` | Ctrl+K inline edit |

## Slash Commands

| Command | Action |
|---------|--------|
| `/new` | New conversation |
| `/clear` | Clear @ context |
| `/reindex` | Rebuild @codebase index |
| `/sync` | Sync knowledge base |
| `/mode agent\|chat\|plan\|ask` | Switch mode |
| `/explorer` | Toggle file tree |
| `/mcp` | MCP server list |
| `/help` | Command help |

## Not Directly Portable from Open References

- Full VS Code editor embedding (needs complete workbench)
- Vendor cloud agents API (needs vendor API key)
- Real-time Tab completion (needs LSP + editor core)

Cache version: **v=17** · After JS/CSS changes, hard refresh (**Ctrl+Shift+R**).
