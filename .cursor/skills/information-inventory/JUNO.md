# Juno 适配 · information-inventory

依据：官方 MCP Sequential Thinking + OpenAI Reasoning best practices（见 SKILL.md 链接）。  
落盘：`.cursor/skills/information-inventory/`；路由见 `config/cc-skills.json`。

## 与本仓库其它部件

| 部件 | 关系 |
|------|------|
| `sequential-thinking` | 分步引擎；本 skill 专管「信息别漏」 |
| 原生 `think` | 情景题审议时应用 think 写下 inventory / coverage |
| `juno-dialogue-anchors` | 只保留口吻原则，**不**放情景标准答案 |
| MEMORY | 只记用户偏好与架构决策，不记考题答案 |

## 人格

仍是 Juno：想清楚后给简洁结论；默认不向用户朗读完整清单。
