# AGENTS.md · 智能体运行协议

本仓库是个人 AI 的「家」。在此项目中运行的 Agent 应遵守以下协议。

## 启动时

1. 读 `USER.md`、`SOUL.md`
2. 若在主会话，读 `MEMORY.md`
3. 任务涉及领域资料时，先查 `knowledge/`

## 记忆

- 重要信息写入 `memory/YYYY-MM-DD.md`（日常）或 `MEMORY.md`（长期）
- 不要只靠对话上下文；**写文件 = 真记忆**
- **对话学习**：用户把聊天记录存到 `knowledge/conversations/`，用 `@agent-memory` 提炼后写入 `MEMORY.md`（非模型训练）

## 任务路由

- 用户 `@my-core-agent` → 读 core skill，再分发到 chat / research / writing / coding / memory
- 用户明确 `@agent-xxx` → 直接执行对应 skill

## 工具使用

- 读写在项目内优先
-  destructive 操作前确认
- 网络搜索：research 类任务可用；用户未要求时不滥用

## 输出

- 默认遵循 USER.md 语言与风格
- 长任务：先简短说明计划，再执行
