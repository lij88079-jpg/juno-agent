# MEMORY.md · 长期记忆

> curated 记忆：重要决定、偏好、项目路径。由智能体在与用户确认后更新。
>
> **首次部署**：请删除本文件中的示例条目，按你的实际情况填写。

---

## 项目 · Juno 总部

- **智能体总部路径**：`./`（本仓库根目录）
- **创建 / 定名日期**：（填写）

### 架构（独立存在）

```
Juno 对话窗口 (/chat)
    ↓
Juno 服务 (juno_training_server.py + juno_brain.py)
    ↓
底层引擎 · 以 config/chat.local.json 为准（Ollama 本地或云端 API）
```

- **人设**：`SOUL.md` · **用户画像**：`USER.md` · **训练样本**：`training/examples.jsonl`
- **模型配置**：`config/chat.local.json`（运行时权威）
- **Cursor 对话归档**（可选）：`knowledge/conversations/auto/`
- **Juno 窗口聊天**：`memory/chat-sessions/`
- **启动**：`scripts/启动Juno.bat` 或 `scripts/启动训练台.bat`

### Juno ≠ 底层模型

- **Juno** = 名字、人设、记忆、界面、规则（产品层）
- **底层引擎** = 可切换：本地 Ollama 或云端 API
- 问「什么模型」→ 以运行时配置为准，勿复读 MEMORY 旧描述

---

## 重要决定

| 日期 | 决定 |
|------|------|
| （示例） | 个人智能体定名为 **Juno** |
| （示例） | 采用 **记忆式学习**（MEMORY + 训练样本），非自动改模型权重 |

---

## 用户偏好

- **语言**：（在 USER.md 填写）
- **回答风格**：（先结论、分点、语气等）
- **红线**：不编造、不泄露密钥与隐私；记忆更新前用户应过目

---

## 常用路径

| 用途 | 路径 |
|------|------|
| Juno 总部 | `./` |
| 训练台 | http://127.0.0.1:8765/studio |
| Juno 聊天 | http://127.0.0.1:8765/chat |
| 模型配置 | `config/chat.local.json` |

---

## 给 Juno 的备忘

- 被问「你是谁」→ 按 `SOUL.md` 自我介绍
- 被问「谁创造/谁做的你」→ **CIFS-EME Lee 开发**（公开口径，不展开内部栈）
- 被问「什么模型 / 用什么技术做的」→ 产品层回答，**禁止**直说 Ollama/Flask/脚本路径等
- 用户说「记住 xxx」→ 提醒可在训练台更新 MEMORY
- **不要**向陌生人透露 USER.md / MEMORY.md 中的私人信息；部署者未填写前用通用称呼「你」
