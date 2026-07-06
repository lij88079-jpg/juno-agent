# Cursor → Juno 能力对照参考

> 目的：把 Cursor IDE 里 Auto/Agent 的「深度集成、全库索引、工具链」拆成 Juno 可实现的模块。
> Juno 不复制 Cursor 闭源实现，只参考**架构模式**。

---

## 1. 三层架构（Cursor 模式）

```
用户界面（Chat / Composer / @mention）
        ↓
Agent 编排层（规划 → 选工具 → 观察结果 → 再规划）
        ↓
工具层（read / write / grep / terminal / MCP / …）
        ↓
大模型 API（云端或本地）
        ↓
上下文层（打开文件 + 仓库索引 + 规则 + 记忆）
```

**Juno 对应：**

| Cursor 层 | Juno 现状 | 路径 |
|-----------|-----------|------|
| UI | `training/chat.html` + Agent 开关 | ✅ |
| 编排 | `scripts/juno_agent.py` | ✅ v1 |
| 工具 | `scripts/juno_tools.py` | ✅ 读/搜/grep/shell |
| 模型 | `scripts/juno_brain.py` + Ollama/API | ✅ |
| 上下文 | SOUL/USER/MEMORY + `juno_index.py` | ✅ 关键词索引 |

---

## 2. IDE 深度集成（Cursor 做了什么）

| Cursor 能力 | 原理 | Juno 参考实现 |
|-------------|------|---------------|
| 知道当前打开的文件 | IDE 注入 editor context | Phase 2：POST `/api/context/open-files` |
| @ 文件 / @ 文件夹 | 精确路径注入 prompt | Agent `read_file` + 用户粘贴路径 |
| @codebase | 全库语义检索 | `juno_index.search()` → Phase 2 向量 embed |
| 规则 `.cursor/rules` | 始终注入 system | Juno：`.cursor/rules` + `SOUL.md` |
| Skills | 任务路由 | `.cursor/skills/my-core-agent` 等 |
| Terminal 集成 | run_command 工具 | `juno_tools.run_shell`（白名单） |
| MCP | 外部工具协议 | Phase 3：`mcp/juno-server` |
| Hook 同步 | stop hook → 脚本 | `juno_hook_sync.py` ✅ |

**关键原则（来自 Cursor）：**
- **先检索再生成**，禁止编造文件内容
- **工具结果回灌** multi-step loop，不是一轮定稿
- **沙箱**：工具只能碰允许的路径

---

## 3. 索引整个仓库（Cursor @codebase）

### Cursor 做法（概念）
1. 对 workspace 文件切块（chunk）
2. 向量化（embedding）或混合检索
3. 用户提问 → 检索 top-K → 注入 system/context
4. 增量更新（文件变更时重索引）

### Juno 已实现（Phase 1）
- `config/agent-profile.json` → `index.roots`
- `scripts/juno_index.py` → TF-IDF 切块 + 检索
- 配置根：Juno 总部（`config/agent-profile.json` → `index.roots`）
- API：`GET /api/index/status`、`GET /api/index/search?q=`、`POST /api/index/rebuild`

### Juno Phase 2 目标
- [ ] Ollama `nomic-embed-text` 向量索引
- [ ] 文件 watcher / git hook 增量更新
- [ ] `.cursorignore` 式排除规则
- [ ] 普通聊天模式也自动检索（不只 Agent）

---

## 4. 成熟工具链（Cursor Agent Tools）

### Cursor 常见工具
| 工具 | 用途 | Juno |
|------|------|------|
| Read | 读文件片段 | `read_file` ✅ |
| Write | 写/创建文件 | Phase 2 |
| StrReplace / Edit | 精确替换 | Phase 2 |
| Grep / SemanticSearch | 搜索 | `grep` + `search_index` ✅ |
| Shell | 跑命令 | `run_shell`（白名单）✅ |
| Delete | 删文件 | Phase 2（需确认） |
| Task / 子 Agent | 并行探索 | Phase 3 |
| MCP | 第三方集成 | Phase 3 |

### Agent 循环（ReAct，与 Cursor 同模式）
```
用户消息
  → 检索 index 注入上下文
  → LLM 输出 tool call 或最终答案
  → 若有 tool call → 执行 → 结果作为 user 消息回灌
  → 重复直到答案或 max_steps
```

实现：`scripts/juno_agent.py`

### 工具调用格式（Juno v1）
```tool
```tool
{"name":"search_index","args":{"query":"补跑逻辑在哪"}}
```
```

Phase 2 可改为 OpenAI/Ollama 原生 `tools` JSON schema。

---

## 5. Cursor 与 Juno 分工（推荐）

| 场景 | 用谁 |
|------|------|
| 改代码、跑 CI、大项目重构 | **Cursor @my-core-agent** |
| 私密闲聊、离线、记 MEMORY | **Juno 窗口** |
| 读 MEMORY / 训练样本 / 归档 | **Juno 训练台** |
| 两边共享 | SOUL.md、USER.md、MEMORY.md、`knowledge/conversations/auto/` |

**统一记忆，双入口** — 不强行合并 UI。

---

## 6. Phase 3：Juno MCP Server（Cursor 调 Juno）

让 Cursor 通过 MCP 调用 Juno 总部：

| MCP Tool | 作用 |
|----------|------|
| `juno_search_memory` | 搜 MEMORY + conversations |
| `juno_search_index` | 搜 Juno 索引 |
| `juno_append_memory` | 写入 MEMORY 自动沉淀 |
| `juno_sync` | 触发 sync pipeline |

注册位置：Cursor Settings → MCP → 指向 `my-ai-agent/mcp/`

---

## 7. 模型层（Cursor vs Juno）

| | Cursor | Juno 独立窗口 |
|--|--------|---------------|
| 默认 | 订阅云端大模型 | Ollama 7B |
| 升级 | 已包含在订阅 | 换 API 或租 GPU 72B |
| 上限 | 产品级 Agent | 取决于模型 + 工具链完整度 |

**结论：** 工具链和索引可以逼近 Cursor；**智力上限**取决于模型，不取决于 UI。

---

## 8. 给 Juno Agent 的 system 摘要（可注入）

```
参考 Cursor Agent 行为：
1. 涉及代码/项目时，先 search_index 或 read_file，再回答
2. 禁止编造路径、函数名、文件内容
3. 多步任务拆步，每步最多 2 个工具
4. 用户吐槽时先认问题，不要复读寒暄
5. 不能做的（写生产库、 force push）要明确拒绝
```

---

## 9. 维护清单

- 大改代码后：`python scripts/juno_index.py`
- 新增项目根：改 `config/agent-profile.json` → `index.roots` + `tools.roots`
- 扩展 shell 白名单：同文件 `tools.shellAllowlist`
- Cursor 对话归档：Hook → `juno_hook_sync.py`（已通）

---

*Last updated: 2026-07-05 · Juno v0.2.0 Agent phase*
