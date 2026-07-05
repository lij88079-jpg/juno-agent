# Juno · Personal AI Agent

> **Beta (v0.1.0)** — Early preview. APIs, prompts, and UI may change without notice.  
> Use at your own discretion; report issues on GitHub.

**Juno** is your private AI HQ: identity, memory, rules, skills, and knowledge base in one folder.

---
## GitHub

```bash
git clone https://github.com/YOUR_USERNAME/juno-agent.git
cd juno-agent
copy config\chat.local.json.example config\chat.local.json   # add your API key
python scripts/juno_training_server.py
# open http://127.0.0.1:8765/chat
```

> **Beta** — not production-ready. Back up `USER.md`, `MEMORY.md`, and `config/chat.local.json` before upgrading.

## 快速开始

1. 用 **Cursor** 打开本文件夹（`文件 → 打开文件夹 → my-ai-agent`）
2. 编辑 **`USER.md`**（你是谁）和 **`SOUL.md`**（AI 是谁）
3. 新开对话，输入 **`@my-core-agent`**，说你的需求
4. 把常用资料丢进 **`knowledge/`** 文件夹

## 独立存在（不用 Cursor、不用云 API）

Juno 可以**完全在你电脑上独立运行**：

1. 安装 [Ollama](https://ollama.com/download)（本地大脑，免费）
2. 双击 **`scripts\启动Juno.bat`** → 自动下载模型 + 打开对话窗口
3. 详细说明见 **`独立存在.txt`**

| 组件 | 作用 |
|------|------|
| **Ollama** | 本地大模型（默认 qwen2.5:7b） |
| **Juno 服务** | 读 SOUL / USER / MEMORY |
| **对话窗口** | 独立聊天界面 |

身份与记忆都在 `my-ai-agent` 文件夹，换电脑拷贝文件夹即可。

## 独立对话窗口（可选云端 API）

双击 **`scripts\打开Juno对话.bat`** → 弹出独立聊天窗口。

- 地址：http://127.0.0.1:8765/chat
- 首次使用：点「API 设置」，填入 **DeepSeek** 或 **OpenAI 兼容** API Key
- Juno 读取 SOUL / USER / MEMORY / 训练样本后回复
- 对话保存在 `memory/chat-sessions/`

## 自动同步 Cursor 对话 + 训练台

**不用手动粘贴了。** 已配置 Cursor 全局 Hook：每次 Agent 结束会自动把聊天记录同步到 `knowledge/conversations/auto/`。

| 操作 | 方式 |
|------|------|
| **打开训练台** | 双击 `scripts/启动训练台.bat`，或 `python scripts/juno_training_server.py` → 浏览器打开 http://127.0.0.1:8765 |
| **手动同步** | 训练台点「立即同步」，或 `python scripts/sync_cursor_chats.py` |
| **全量重扫** | `python scripts/sync_cursor_chats.py --force` |

训练台可以：查看已同步对话、编辑 MEMORY / USER、添加「理想问答」训练样本（存 `training/examples.jsonl`）。

让 Juno 消化新对话：在 Cursor 里说 `@agent-memory 总结 conversations/auto 最新记录，更新 MEMORY 草案`

> 这是**记忆式学习**（RAG + MEMORY + 训练样本），不是改模型权重。

## 目录结构

```
my-ai-agent/
├── USER.md              ← 你的画像（必改）
├── SOUL.md              ← AI 人设（必改）
├── MEMORY.md            ← 长期记忆
├── AGENTS.md            ← 智能体运行协议
├── .cursor/
│   ├── rules/           ← 总控规则（打开本项目时自动生效）
│   └── skills/          ← 项目内技能
├── knowledge/           ← 你的知识库（PDF、笔记、文档）
│   └── conversations/auto/  ← Cursor 对话自动同步（勿手改）
├── training/            ← 训练台 UI + examples.jsonl
├── scripts/             ← sync_cursor_chats.py、训练台服务
├── memory/daily/        ← 每日日志（可选）
└── config/              ← sync-state.json 等
```

## 在任何项目里使用

全局技能已安装到：`C:\Users\solut xc\.cursor\skills\my-core-agent\`

在其他文件夹工作时也可以 **`@my-core-agent`**，它会读取本项目的 `USER.md` / `MEMORY.md`（若你告知路径或在本项目内对话）。

## 扩展

| 想加什么 | 怎么做 |
|----------|--------|
| 新专长 | 在 `.cursor/skills/` 新建文件夹 + `SKILL.md` |
| 新规矩 | 在 `.cursor/rules/` 新建 `.mdc` |
| 新知识 | 放进 `knowledge/` 并在对话里 @ 文件 |
| 换名字/性格 | 改 `SOUL.md` |

## 第一次使用

阅读 **`BOOTSTRAP.md`**，完成初始化后可删除该文件。
