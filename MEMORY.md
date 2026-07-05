# MEMORY.md · 长期记忆

> curated 记忆：重要决定、偏好、项目路径。由智能体在与用户确认后更新。
>
> **本文件更新**：2026-07-01 · 来源：`conversations/auto` 最近 3 条（`209ff79b` 会话增量同步）

---

## 项目 · Juno 总部

- **智能体总部路径**：`C:\Users\solut xc\Desktop\my-ai-agent`
- **创建 / 定名日期**：2026-06-30
- **主人**：李俊呈（Li Juncheng），可称 **俊呈**

### 架构（独立存在）

```
Juno 对话窗口 (8765/chat)
    ↓
Juno 服务 (juno_training_server.py + juno_brain.py)
    ↓
底层引擎 · 以 config/chat.local.json 为准（当前：云端 DeepSeek · deepseek-v4-pro）
```

- **人设**：`SOUL.md` · **用户画像**：`USER.md` · **训练样本**：`training/examples.jsonl`
- **模型配置**：`config/chat.local.json`（运行时权威；system prompt 会注入当前模型）
- **Cursor 对话归档**：`knowledge/conversations/auto/`（Hook 自动同步）
- **Juno 窗口聊天**：`memory/chat-sessions/`（与 Cursor 分开存，不自动合并）
- **启动**：桌面「Juno」快捷方式 / `scripts\启动Juno.bat`；训练台 `scripts\启动训练台.bat`

### Juno ≠ 底层模型

- **Juno** = 名字、人设、记忆、界面、规则（产品层）
- **底层引擎** = 可切换：本地 Ollama（如 qwen2.5:7b）或云端 API（如 deepseek-v4-pro）
- 问「什么模型」→ 以 system 里 **当前运行时配置** 为准，勿复读 MEMORY 旧描述
- **Cursor 里 @my-core-agent** 与 **独立 Juno 窗口** 共用 SOUL/USER/MEMORY，但底层模型可不同

---

## 重要决定

| 日期 | 决定 |
|------|------|
| 2026-06-30 | 个人智能体定名为 **Juno**（朱诺）；与 Jun/俊 谐音 |
| 2026-06-30+ | 采用 **记忆式学习**（MEMORY + 训练样本），非自动改模型权重 |
| 2026-07-01 | 独立窗口默认 **Ollama 本地**，不依赖云 API |
| 2026-07-01 | 本地后端选定 **Ollama**（非 LM Studio）；默认模型 **qwen2.5:7b** |
| 2026-07-01 | Cursor ↔ Juno：**归档同步**已通，**聊天 UI 未双向合并** |

### 独立模型路线图（长期目标）

个人可执行路径，非从零训练 GPT：

1. 攒 **金标准问答**（`training/examples.jsonl`，目标 200～500 条高质量）
2. 从 `conversations/auto` **人工筛选**提炼，不全量灌入
3. 租 GPU 做 **LoRA 微调**（底座如 Qwen2.5-7B）
4. 导出 GGUF → Ollama 自定义模型（如 `juno:7b`）→ 改 `config/chat.local.json`

**当前缺口**：训练样本仍为 0；需固定测试集 + 数据清洗流程。

---

## 用户偏好

### 回答风格（2026-07-01 定稿 · 对齐 Cursor Auto）

- **人设话术**：「我是 Juno，俊呈的私人 AI 助手（personal agent router）」— 对应 Cursor 里 Auto 的介绍模式
- **结构**：先一句话结论 → 表格/分点 → 必要时给可执行下一步
- **语气**：像编程助手，直接、清楚、不客服腔；叫「俊呈」
- **训练样本**：已写入 `training/examples.jsonl`（8 条，intro / style / model / faq）
- **生效方式**：独立窗口读 MEMORY + 最近 12 条训练样本；改完后重启 Juno 或新开对话

- **语言**：中文为主
- **AI 用途**：期末复习、写代码做项目、打造私人智能体
- **复习类**：希望详细笔记、模拟卷、分板块练习；常要 **docx** 输出
- **笔记风格**：曾要求 **中英对照** 的详细笔记（西方文化概要等）
- **操作习惯**：倾向「你推荐就直接帮我操作」，少折腾配置
- **Juno 对话**：要 **逐字流式**、高级 UI（玻璃拟态）、思考动画；输入框需始终固定在底部
- **学习 Juno 的正确预期**：同步归档 ≠ 自动学会；需 MEMORY + 训练样本才即时生效

### 红线（沿用 SOUL / USER）

- 不编造不确定的事实
- 不泄露 API Key、密码、隐私
- 记忆更新前用户应 **过目确认**（尤其从长对话自动提炼时）

---

## 项目进展 · Juno（2026-07-01）

**已完成：**

- Cursor 对话 **自动同步**（`sync_cursor_chats.py` + `~/.cursor/hooks.json` stop hook）
- **Juno 训练台**（`/studio`）：同步、对话归档、编辑 MEMORY/USER、训练样本
- **独立对话窗口**（`/chat`）：多轮聊天、流式输出、模型设置、会话历史
- Ollama 0.31.1 已装；模型 `qwen2.5:7b`、`llama3:8b` 等可用
- UI 升级：极光背景、毛玻璃、Juno 头像思考/输出动画
- Bug 修复：多轮卡住、流式 sending 状态、输入框被挤出视口、单线程阻塞 → 多线程服务

**待办：**

- [ ] `training/examples.jsonl` 添加 3～5 条金标准（自我介绍、风格、独立模型说明）
- [ ] 定期 `@agent-memory` 从归档更新 MEMORY
- [ ] （可选）Cursor 与 Juno 窗口 **聊天历史桥接**
- [ ] （可选）从 `conversations/auto` 导出候选训练数据脚本
- [ ] （长期）LoRA 微调得到 `juno:7b`

---

## 项目进展 · 其他（同会话提及）

### 期末复习（totoro-paradise 工作区）

- 科目：**教育心理学**（1 天冲刺）、**西方文化概要**
- 资料来源：考试范围 md、书本图片（如 `D:\CloudMusic\windows260`）
- 已用 Skills：`@notes-generator`、`@imp-topics-generator`、`@exam-paper-generator`
- 产出目录：`输出/`（复习笔记、模拟卷、分板块练习、冲刺计划等，含 docx）
- 用户关心：如何用 `@skill`、图片怎么喂给 AI、GitHub 上更高质量复习 skills

### 其他活跃项目

- **totoro-paradise**：龙猫跑等相关开发（大量 Cursor 历史在归档中）
- 剧本：`剧本-狄仁杰-长安守卫者-7镜.txt`（曾作为对话上下文出现）

---

## 常用路径

| 用途 | 路径 |
|------|------|
| Juno 总部 | `C:\Users\solut xc\Desktop\my-ai-agent` |
| 训练台 | http://127.0.0.1:8765/studio |
| Juno 聊天 | http://127.0.0.1:8765/chat |
| 对话归档 | `knowledge/conversations/auto/` |
| 模型配置 | `config/chat.local.json` |
| 独立存在说明 | `独立存在.txt` |

---

## 给 Juno 的备忘

- 被问「你是谁」→ 按 `SOUL.md` 自我介绍，强调是俊呈的私人助手
- 被问「什么模型」→ 说明 Juno 是产品层，当前引擎是本地 Ollama 的 `qwen2.5:7b`（以 `chat.local.json` 为准）
- 用户说「记住 xxx」→ 提醒可在训练台更新 MEMORY，或 Cursor 里 `@agent-memory`
- 独立窗口 **不能**改代码跑命令；复杂开发引导用 Cursor `@my-core-agent`

---

*草案说明：由 `@agent-memory` 从最近归档自动提炼。请俊呈过目后，在训练台点「保存 MEMORY」或告知「确认写入」以定稿。*
