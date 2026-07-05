# 对话记录 · Conversations

Juno 的历史对话来源：**自动同步** + 可选手动归档。

## 自动同步（推荐）

**两路来源都会进 `knowledge/conversations/auto/`：**

1. **Cursor 对话** — 全局 Hook（`~/.cursor/hooks.json`）在 Agent 结束时运行 `sync_cursor_chats.py`
2. **Juno 网页对话** — 每次在 `http://127.0.0.1:8765/chat` 聊完一轮，后台自动：
   - `sync_juno_chats.py` → `juno-{sessionId}.md`
   - `juno_auto_learn.py` → 写入 `memory/daily/`、关键词「记住」进 `MEMORY.md`、优质问答进 `training/examples.jsonl`
   - 顺带增量同步 Cursor 对话

手动全量：

```bash
python scripts/juno_sync_pipeline.py --all
python scripts/sync_juno_chats.py
python scripts/sync_cursor_chats.py
```

或在 **Juno 训练台**（`scripts/启动训练台.bat`）点「立即同步」。

## 手动归档（可选）

仍可在本目录手动新建 `YYYY-MM-DD-主题.md`，用于整理、删减后的精华版。

## 让 Juno「学习」

同步或保存对话后，在 Cursor 说：

```
@agent-memory

请阅读 knowledge/conversations/auto/ 最新文件，提炼对我的了解，更新 MEMORY.md（经我确认后再写）
```

或在训练台添加 **训练样本**（理想问答对），Juno 会参考 `training/examples.jsonl`。

## 不要放什么

- API Key、密码、完整身份证/银行卡
- 他人隐私（未经同意）

## 说明

这不是机器学习 fine-tune，而是 **记忆 + 总结 + 训练样本**：稳定偏好与项目上下文写入 `MEMORY.md`，下次对话自动参考。
