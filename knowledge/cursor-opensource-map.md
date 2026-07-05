# Cursor 开源仓库 → Juno 对照实现

> Cursor IDE 本体闭源，但 **cursor/** GitHub org 与社区 VS Code fork 有可对齐的开源参考。Juno 按这些仓库对照实现。

## 官方开源仓库（github.com/cursor）

| 仓库 | 用途 | Juno 实现 |
|------|------|-----------|
| [cursor/agent-trace](https://github.com/cursor/agent-trace) | 行级 AI 归因、Trace Record、line ranges | `scripts/juno_agent_trace.py` · `.agent-trace/traces.jsonl` · Review 行号 diff |
| [cursor/cookbook/sdk/agent-kanban](https://github.com/cursor/cookbook) | 多 Agent 并行看板、Cloud Agents 卡片 | `#agents-drawer` 右侧 Agents 面板 · subagent tabs |
| [cursor/cookbook/sdk/dag-task-runner](https://github.com/cookbook) | 子任务 DAG 编排 | `scripts/juno_subagent.py` · `task` 工具 |
| [cursor/cookbook/sdk/coding-agent-cli](https://github.com/cursor/cookbook) | Shell 输出 / CLI 模式 | `#terminal-panel` · `cursor-terminal.js` |
| [cursor/mcp-servers](https://github.com/cursor/mcp-servers) | MCP 官方示例 | `config/mcp-inbound.json` · `#mcp-modal` · 合并 `~/.cursor/mcp.json` |
| [cursor/plugins](https://github.com/cursor/plugins) | 插件模板 | 参考 rules/skills 注入 |

## 社区 IDE / Agent UI 参考

| 项目 | 可借鉴点 | Juno |
|------|----------|------|
| [voideditor/void](https://github.com/voideditor/void) | VS Code fork、Cursor 式 Agent 侧栏 | Activity Bar + chat-panel 布局 |
| [njbinbin-piscis/AgentZ](https://github.com/njbinbin-piscis/AgentZ) | Cmd+K inline diff、AssistantPanel | `cursor-cmdk.js` · composer-v2 |
| [continue-dev/continue](https://github.com/continuedev/continue) | @context、索引、slash 命令 | `@mention` 六 tab · `/` 斜杠命令 |
| [21st-dev/agent-elements](https://github.com/21st-dev/agent-elements) | EditTool diff + approval UI | Review bar · hunk Accept/Reject |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) | Thread + Composer 组件 | composer-v2 · streaming rail |

## 能力对照（v17 注入状态）

| Cursor 能力 | Juno | 状态 |
|-------------|------|------|
| Agent 工具链 | `juno_agent.py` + tools | ✅ |
| Chat / Agent / Plan / Ask 模式 | `resolve_ui_mode()` | ✅ |
| Thinking / reasoning 流 | `reasoning_delta` → Thought 面板 | ✅ |
| @file / @codebase | mention picker | ✅ |
| @Rules / @Docs / @Folder | `GET /api/mention/sources` | ✅ v17 |
| @Git / @Web | git status 注入 · web 提示 | ✅ v17 |
| `/` 斜杠命令 | `cursor-slash.js` | ✅ v17 |
| 文件资源管理器 | `cursor-explorer.js` · `GET /api/tools/tree` | ✅ v17 |
| MCP 管理 UI | `cursor-mcp-modal.js` | ✅ v17 |
| Review + Monaco diff | `cursor-diff-editor.js` | ✅ |
| Cmd+K inline edit | `cursor-cmdk.js` | ✅ |
| 终端输出面板 | `cursor-terminal.js` | ✅（只读，非 PTY） |
| Subagent / task | `juno_subagent.py` | ✅ |
| Rules / Skills 注入 | `juno_skills.py` | ✅ |
| IDE 打开文件上下文 | `memory/ide-context.json` | ✅ |
| 完整 VS Code workbench | — | ❌ 需桌面 IDE |
| Shadow Workspace 索引 | — | ❌ Cursor 专有 |
| 交互式 PTY 终端 | — | ⏳ 待 xterm.js |

## API（新增 v17）

- `GET /api/tools/tree?path=&depth=2` — 文件树（Explorer）
- `GET /api/mention/sources?kind=rules|docs|folder|git|web|files&q=` — 扩展 @mention
- `GET /api/mcp/servers` — MCP 列表（UI 弹窗）

## 前端模块（training/）

| 文件 | 作用 |
|------|------|
| `cursor-ui.js` | Review · Agents · @mention 六 tab |
| `cursor-explorer.js` | 左侧资源管理器 |
| `cursor-slash.js` | `/new` `/mode` `/reindex` 等 |
| `cursor-mcp-modal.js` | MCP 服务器弹窗 |
| `cursor-diff-editor.js` | Monaco side-by-side diff |
| `cursor-terminal.js` | Shell 输出面板 |
| `cursor-cmdk.js` | Ctrl+K inline edit |

## 斜杠命令

| 命令 | 作用 |
|------|------|
| `/new` | 新对话 |
| `/clear` | 清空 @ 上下文 |
| `/reindex` | 重建 @codebase 索引 |
| `/sync` | 同步知识库 |
| `/mode agent\|chat\|plan\|ask` | 切换模式 |
| `/explorer` | 开关文件树 |
| `/mcp` | MCP 服务器列表 |
| `/help` | 命令帮助 |

## 仍无法用开源直接移植

- VS Code 编辑器内嵌（需完整 workbench）
- Cloud Agents API（需 Cursor API key）
- 实时代码补全 Tab（需 LSP + 编辑器内核）

缓存版本：**v=17** · 改 JS/CSS 后 **Ctrl+Shift+R** 强刷。
